"""Objects: what a thing weighs and how it behaves, how big something in a picture is, and an honest record of
what was made out about it.

weigh    mass, centre of gravity and tipping from a shape, its size and what it is made of
measure  the real size of something in a picture, from an object of known size in the same picture
analyse  a record that keeps apart what was seen, measured, decoded and inferred, and what stays unknown

Densities and reference sizes are tables of typical and standard values (data/materials.json,
data/references.json), labelled as such. Nothing here is a sensor: 'analyse' records what was made out from
a picture or a description that someone supplied, and says so.
"""
import math
import re

from .core import G, command, die, driver, fold, load_data, more, num, rec, table, trim, unprotect

UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
SHAPES = ("box", "cylinder", "tube", "sphere", "volume")
# Design accelerations for securing a load on a road vehicle, as fractions of g: EN 12195-1, as the European
# Commission's cargo securing guidelines (2014) quote it. Sideways it is 0.5 against sliding and 0.6 against tipping.
FORWARD_G, SIDEWAYS_G, REARWARD_G, TIPPING_G = 0.8, 0.5, 0.5, 0.6
# Reference masses for lifting in ideal conditions, ISO 11228-1:2021: 25 kg for men aged 20 to 45, 20 kg for women of
# that age and for younger and older men, 15 kg for younger and older women. 25 kg is the most it gives for anyone.
LIFT_LOW_KG, LIFT_HIGH_KG = 15.0, 25.0
CONFIDENCE = ("low", "medium", "high")
SOURCES = {
    "photo": "a photograph supplied by %s",
    "video": "a video supplied by %s",
    "description": "a description given by %s",
    "document": "a document supplied by %s",
    "sim": "the simulation's own sensors, as the brief and 'scan' allow",
}


def materials():
    return load_data("materials")["materials"]


def material(name):
    data = materials()
    key = fold(name)
    if key in data:
        return key, data[key]
    import difflib
    near = difflib.get_close_matches(key, list(data), n=3, cutoff=0.6)
    die("no material called '%s'.%s 'weigh --list' shows them all; or give --density in kg/m3" % (
        name, " Did you mean: %s?" % ", ".join(near) if near else ""))


def _sizes(text, factor, count, what):
    parts = re.split(r"\s*[xX]\s*", unprotect(str(text)).strip())
    try:
        vals = [float(p) * factor for p in parts]
    except ValueError:
        vals = []
    if len(vals) != count or any(v <= 0 for v in vals):
        die(what)
    return vals


def segment(fill):
    """A lying cylinder part full: (depth of liquid, height of its centre of gravity above the lowest point),
    both as fractions of the inside diameter."""
    if fill >= 1.0:
        return 1.0, 0.5
    lo, hi = 0.0, 2.0 * math.pi
    for _ in range(60):                                     # the chord's angle whose segment holds that share of the circle
        mid = (lo + hi) / 2.0
        if (mid - math.sin(mid)) / (2.0 * math.pi) < fill:
            lo = mid
        else:
            hi = mid
    theta = (lo + hi) / 2.0
    depth = (1.0 - math.cos(theta / 2.0)) / 2.0
    off = 4.0 * math.sin(theta / 2.0) ** 3 / (3.0 * (theta - math.sin(theta)))      # centroid below the centre, in radii
    return depth, (1.0 - off) / 2.0


def _spread(mass, low, high):
    if low is None or high is None or abs(high - low) < 1e-9:
        return "%s kg" % _kg(mass)
    return "%s kg (%s to %s)" % (_kg(mass), _kg(low), _kg(high))


def _kg(x):
    return num(x) if x >= 100 else trim(x, 1) if x >= 10 else trim(x, 2)


def _pull(x):
    return num(x) if x >= 10 else trim(x, 1)


def _mm(x):
    return num(x) if x >= 1000 else trim(x, 0) if x >= 100 else trim(x, 1)


def cmd_weigh(a):
    if a.list:
        data = load_data("materials")
        rows = []
        for kind in data["kinds"]:
            for key, m in data["materials"].items():
                if m["kind"] == kind:
                    span = "%s to %s" % (num(m["low"]), num(m["high"])) if "low" in m else ""
                    rows.append((key, kind, num(m["kg_m3"]), span, m["is"]))
        rec("MATERIALS", "%d, typical densities in kg/m3 [table]" % len(rows))
        table(rows, header=("material", "kind", "kg/m3", "varies", "what"), indent=2, right=(2,))
        rec("SHAPES", "box LxWxH, cylinder DxH, tube DxL (with --wall), sphere D, volume 80l or 0.5m3")
        rec("NOTE", "typical values, not measurements: wood, stone, sand and soil vary with water and with where they came from. "
                    "Weigh it if it matters; --density takes a figure of your own")
        return
    if not a.shape or not a.size:
        die("weigh takes a shape and its size: box 1200x800x600, cylinder 580x880, tube 60x3000, sphere 300, volume 80l ('weigh --list')")
    shape = a.shape.lower()
    if shape not in SHAPES:
        die("a shape is one of: %s" % ", ".join(SHAPES))
    factor = UNIT_MM[a.unit]
    if a.count < 1:
        die("--count is at least 1")
    wall = a.wall * factor if a.wall is not None else None
    if wall is not None and wall <= 0:
        die("--wall is the thickness of the wall, more than zero")
    # the material of the thing itself
    dens = low = high = None
    made_of = ""
    if a.density is not None:
        if not 1 <= a.density <= 25000:
            die("--density is in kg per cubic metre, between 1 and 25,000")
        dens, made_of = a.density, "%s kg/m3 [as given]" % num(a.density)
    elif a.material:
        key, m = material(a.material)
        dens, low, high = float(m["kg_m3"]), m.get("low"), m.get("high")
        made_of = "%s, %s kg/m3%s [table: typical]" % (m["is"], num(dens), " (%s to %s)" % (num(low), num(high)) if low else "")
    if dens is None and a.mass is None:
        die("what is it made of? --material oak ('weigh --list'), --density in kg/m3, or its --mass if you know it")

    # geometry, in mm
    lying = bool(a.lying)
    base = None                 # (along, across) of the footprint, or one diameter
    height = None
    if shape == "volume":
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(l|litres?|liters?|m3|dm3|cm3|ml)?\s*$", unprotect(str(a.size)).lower())
        if not m:
            die("a volume is a number with l or m3: 80l, 0.5m3")
        outer = float(m.group(1)) * {"l": 1e-3, "litre": 1e-3, "litres": 1e-3, "liter": 1e-3, "liters": 1e-3, "m3": 1.0, "dm3": 1e-3,
                                     "cm3": 1e-6, "ml": 1e-6}[m.group(2) or "l"]
        inner = 0.0
        if wall is not None or a.fill or lying:
            die("a bare volume has no walls, no filling and no way up: give a shape for those")
        label = "%s litres" % num(outer * 1000.0) if outer < 1 else "%s m3" % trim(outer, 3)
    elif shape == "box":
        length, width, height = _sizes(a.size, factor, 3, "a box is length x width x height, such as 1200x800x600")
        if lying:
            die("--lying is for a cylinder or a tube: turn a box by giving its sizes the other way round")
        outer = length * width * height / 1e9
        inner = 0.0
        if wall is not None:
            if min(length, width, height) <= 2 * wall:
                die("the wall is thicker than half the smallest side")
            inner = (length - 2 * wall) * (width - 2 * wall) * (height - 2 * wall) / 1e9
        base = (max(length, width), min(length, width))
        label = "box %s x %s x %s mm" % (_mm(length), _mm(width), _mm(height))
    elif shape in ("cylinder", "tube"):
        dia, length = _sizes(a.size, factor, 2, "a %s is diameter x %s, such as %s" % (
            shape, "length" if shape == "tube" else "height", "60x3000" if shape == "tube" else "580x880"))
        if shape == "tube" and wall is None:
            die("a tube needs its wall thickness: --wall 4")
        outer = math.pi * dia * dia / 4.0 * length / 1e9
        inner = 0.0
        if wall is not None:
            ends = 0.0 if shape == "tube" else 2 * wall
            if dia <= 2 * wall or length <= ends:
                die("the wall is thicker than the %s allows" % shape)
            inner = math.pi * (dia - 2 * wall) ** 2 / 4.0 * (length - ends) / 1e9
        if lying:
            base, height = (length, 0.0), dia
        else:
            base, height = (dia,), length
        label = "%s %s mm across, %s mm %s%s" % (shape, _mm(dia), _mm(length), "long" if lying or shape == "tube" else "tall",
                                               ", lying" if lying else "")
    else:
        (dia,) = _sizes(a.size, factor, 1, "a sphere is one size, its diameter: 300")
        outer = math.pi * dia ** 3 / 6.0 / 1e9
        inner = 0.0
        if wall is not None:
            if dia <= 2 * wall:
                die("the wall is thicker than the sphere allows")
            inner = math.pi * (dia - 2 * wall) ** 3 / 6.0 / 1e9
        height = dia
        label = "sphere %s mm across" % _mm(dia)
    solid = outer - inner if wall is not None else outer
    if wall is not None:
        label += ", hollow, walls %s mm" % _mm(wall)

    # what is inside it
    contents = c_low = c_high = 0.0
    fill_share, fill_text = 0.0, ""
    if a.fill:
        if wall is None:
            die("--fill needs something hollow: give --wall as well")
        name, _, pct = a.fill.partition(":")
        try:
            fill_share = float(pct) / 100.0 if pct else 1.0
        except ValueError:
            die("--fill is MATERIAL or MATERIAL:PERCENT, such as water:80")
        if not 0 < fill_share <= 1:
            die("the filling is more than 0 and at most 100 per cent")
        if shape == "sphere" and fill_share < 1:
            die("a part-filled sphere is not worked out here: give --mass, or fill it")
        fkey, fm = material(name)
        contents = inner * fill_share * fm["kg_m3"]
        c_low, c_high = inner * fill_share * fm.get("low", fm["kg_m3"]), inner * fill_share * fm.get("high", fm["kg_m3"])
        fill_text = "%s, %s litres at %s kg/m3%s" % (fm["is"], num(inner * fill_share * 1000.0), num(fm["kg_m3"]),
                                                   "" if fill_share >= 1 else ", %s%% full" % trim(fill_share * 100.0, 0))

    rec("ITEM", "%s%s" % (label, "; %s" % made_of if made_of else ""))
    if wall is not None:
        rec("VOLUME", "%s m3 of material, %s litres inside [derived]" % (trim(solid, 4 if solid < 1 else 2), num(inner * 1000.0)))
    else:
        rec("VOLUME", "%s m3 (%s litres) [derived]" % (trim(outer, 4 if outer < 1 else 2), num(outer * 1000.0)))
    if a.mass is not None:
        if a.mass <= 0:
            die("--mass is in kg, more than zero")
        mass, m_low, m_high = float(a.mass), None, None
        shell = max(0.0, mass - contents)
        rec("MASS", "%s kg [as given]" % _kg(mass))
        if dens is not None and not a.fill and solid > 0:
            implied = mass / solid
            lo_ok, hi_ok = (low or dens) * 0.85, (high or dens) * 1.15
            if not lo_ok <= implied <= hi_ok:
                more("that makes it %s kg/m3, where %s runs near %s: the size, the mass or the material is off" % (
                    num(implied), a.material or "the density given", num(dens)))
    else:
        shell = solid * dens
        mass = shell + contents
        m_low = solid * (low if low is not None else dens) + c_low
        m_high = solid * (high if high is not None else dens) + c_high
        if a.fill:
            rec("MASS", "%s: %s empty, %s of %s [derived]" % (_spread(mass, m_low, m_high), "%s kg" % _kg(shell), "%s kg" % _kg(contents), fill_text))
        else:
            rec("MASS", "%s [derived]" % _spread(mass, m_low, m_high))
    if a.count > 1:
        rec("TOGETHER", "%d of them: %s [derived]" % (a.count, _spread(mass * a.count, m_low * a.count if m_low is not None else None,
                                                                    m_high * a.count if m_high is not None else None)))
    if shape == "volume":
        _weigh_next(mass, a.count, None)
        return

    # centre of gravity: the thing itself is even all through; what is in it settles to the bottom
    z_shell = height / 2.0
    z = z_shell
    if contents > 0:
        if shape == "sphere":
            z_fill = dia / 2.0
        elif lying:
            _, frac = segment(fill_share)
            z_fill = wall + frac * (dia - 2 * wall)
        else:
            ends = 0.0 if shape == "tube" else wall
            z_fill = ends + fill_share * (height - 2 * ends) / 2.0
        z = (shell * z_shell + contents * z_fill) / (shell + contents)
    rec("LIES" if lying else "STANDS", "%s mm %s; centre of gravity %s mm up%s [derived]" % (
        _mm(height), "high" if lying else "tall", _mm(z), ", pulled down by what is in it" if contents > 0 and z < z_shell - 0.5 else ""))

    def tip(half, way):
        need = half / z
        angle = math.degrees(math.atan(need))
        return need, "%s: %s deg, or %s g" % (way, trim(angle, 0), trim(need, 2))

    rolls = shape == "sphere" or lying
    tips = []
    if shape == "box":
        tips = [tip(base[1] / 2.0, "over its long edge"), tip(base[0] / 2.0, "over its short edge")]
        if abs(base[0] - base[1]) < 1e-9:
            tips = [tip(base[0] / 2.0, "over any edge")]
    elif shape in ("cylinder", "tube") and not lying:
        tips = [tip(base[0] / 2.0, "any way")]
    if tips:
        rec("TIPS", "; ".join(t[1] for t in tips) + " [derived]")
        weakest = min(t[0] for t in tips)
        if weakest < TIPPING_G:
            more("top-heavy: it goes over in a bend or under braking unless it is held upright. Lay it down, or strap it high")
        elif weakest < FORWARD_G:
            more("stands through a bend, but braking can tip it if its short side lies along the car: turn it, or strap it")
        else:
            more("squat enough to stay upright; it will slide long before it tips, so it still needs holding")
        if a.mu is not None:
            if not 0 < a.mu <= 1.5:
                die("--mu is the friction between the thing and the floor, usually 0.2 to 0.6")
            if a.mu < weakest:
                rec("SLIDES", "at %s g, before it would tip: on this floor it slides first [derived; friction %s as given]" % (trim(a.mu, 2), trim(a.mu, 2)))
            else:
                rec("SLIDES", "not before it tips: with friction %s it goes over at %s g rather than slide [derived]" % (trim(a.mu, 2), trim(weakest, 2)))
    if rolls:
        rec("ROLLS", "it has no flat to stand on%s: chock it or strap it, whatever it weighs" % (" across its length" if lying else ""))
    rec("HOLD", "%s N forwards under braking, %s N sideways in a bend: what the restraint must take, about %s and %s kg of pull "
                "[derived: mass x %s g and %s g, the design figures of EN 12195-1 for loads on road vehicles]" % (
                    num(mass * FORWARD_G * G), num(mass * SIDEWAYS_G * G), _pull(mass * FORWARD_G), _pull(mass * SIDEWAYS_G),
                    trim(FORWARD_G, 1), trim(SIDEWAYS_G, 1)))
    more("loose in a 50 km/h crash it arrives at whatever stops it as if dropped from %s m [derived: v2 / 2g]" % trim((50 / 3.6) ** 2 / (2 * G), 1))
    scale = "the reference masses for one person lifting in ideal conditions run from %s to %s kg by age and sex [ISO 11228-1]" % (
        trim(LIFT_LOW_KG, 0), trim(LIFT_HIGH_KG, 0))
    if mass <= LIFT_LOW_KG:
        rec("LIFT", "%s kg: under all of them; %s. Ideal means held close, at waist height: less at arm's length, from the floor "
                    "or overhead" % (_kg(mass), scale))
    elif mass <= LIFT_HIGH_KG:
        rec("LIFT", "%s kg: within them for some people and above them for others; %s. Ideal means held close, at waist height" % (
            _kg(mass), scale))
    else:
        rec("LIFT", "%s kg: above the highest of them; %s. Share it, or use a trolley, a ramp or a hoist" % (_kg(mass), scale))
    dims = None
    if shape == "box":
        dims = (length, width, height)
    elif shape in ("cylinder", "tube"):
        dims = (length, dia, dia) if lying else (dia, dia, length)
    elif shape == "sphere":
        dims = (dia, dia, dia)
    _weigh_next(mass, a.count, dims)


def _weigh_next(mass, count, dims):
    total = mass * count
    line = "load ... --cargo %s%s" % (trim(total, 0) if total >= 10 else trim(total, 1), "" if count == 1 else " (all %d)" % count)
    if dims:
        line += " | fit --space LxWxH --item %sx%sx%s%s" % (trim(dims[0], 0), trim(dims[1], 0), trim(dims[2], 0), ":%d" % count if count > 1 else "")
    rec("NEXT", line)


# ---- measure

def _reference(text):
    """'card', 'plate-eu', '520mm', '1.2m' -> (mm, what, source)."""
    refs = load_data("references")["references"]
    t = unprotect(str(text)).strip().lower()
    key = t.replace("_", "-").replace(" ", "-")
    if key in refs:
        r = refs[key]
        return float(r["mm"]), r["is"], r["source"]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mm|cm|m|in)$", t)
    if m:
        return float(m.group(1)) * UNIT_MM[m.group(2)], "a length of %s %s" % (m.group(1), m.group(2)), "as given"
    import difflib
    near = difflib.get_close_matches(key, list(refs), n=3, cutoff=0.5)
    die("'%s' is neither a reference object nor a size with its unit (520mm, 1.2m).%s 'measure --list' shows the objects" % (
        text, " Did you mean: %s?" % ", ".join(near) if near else ""))


def _pair(text, what):
    name, sep, val = unprotect(str(text)).rpartition("=")
    try:
        px = float(val)
    except ValueError:
        px = -1.0
    if not sep or not name.strip() or px <= 0:
        die("%s looks like NAME=LENGTH, with the length as it measures in the picture: \"%s\"" % (what, "wheel=268"))
    return name.strip(), px


def _length(mm):
    if mm >= 1000:
        return "%s m" % trim(mm / 1000.0, 2)
    if mm >= 100:
        return "%s mm" % trim(mm, 0)
    return "%s mm" % trim(mm, 1)


def cmd_measure(a):
    if a.list:
        refs = load_data("references")["references"]
        rows = [(k, _length(r["mm"]), r["is"], r["source"]) for k, r in refs.items()]
        rec("OBJECTS", "%d things of a standard size [table]" % len(rows))
        table(rows, header=("name", "size", "what", "source"), indent=2, right=(1,))
        rec("OR", "any size of your own with its unit: --ref 520mm=212, --ref 1.2m=340")
        return
    if not a.ref or not a.px:
        die("measure needs the reference and what to measure: --ref card=212 --px wheel=268 (lengths as they measure in the picture)")
    ref_name, ref_px = _pair(a.ref, "--ref")
    mm, what, source = _reference(ref_name)
    if a.err < 0:
        die("--err is how far out a reading from the picture might be, in the same units as the readings")
    scale = mm / ref_px
    rec("SCALE", "%s: %s over %s in the picture, so 1 in the picture is %s mm [%s]" % (what, _length(mm), trim(ref_px, 1), trim(scale, 4), source))
    for item in a.px:
        name, px = _pair(item, "--px")
        size = px * scale
        if a.err:
            rel = math.sqrt((a.err / ref_px) ** 2 + (a.err / px) ** 2)
            rec(name.upper(), "%s in the picture = %s, give or take %s [measured from the picture]" % (trim(px, 1), _length(size), _length(size * rel)))
        else:
            rec(name.upper(), "%s in the picture = %s [measured from the picture]" % (trim(px, 1), _length(size)))
    rec("NOTE", "true only if the reference and the thing measured are the same distance from the camera and both face it squarely. "
                "Anything nearer looks bigger and anything turned away looks shorter, and a wide lens bends the edges: say so with the figure")


# ---- analyse

def _split(text, seps):
    for sep in seps:
        head, found, tail = str(text).partition(sep)
        if found and head.strip() and tail.strip():
            return head.strip(), tail.strip()
    return str(text).strip(), ""


def cmd_analyse(a):
    source = a.source.lower()
    if source not in SOURCES:
        die("--source is one of: %s" % ", ".join(SOURCES))
    seen = [s.strip() for s in (a.seen or []) if s.strip()]
    measured = [_split(m, ("=",)) for m in (a.measured or [])]
    decoded = [_split(m, ("=",)) for m in (a.decoded or [])]
    inferred = []
    for text in a.inferred or []:
        claim, _, sure = str(text).rpartition(":")
        if sure.strip().lower() not in CONFIDENCE or not claim.strip():
            die("an inference says how sure it is: \"likely a long-wheelbase van: medium\" (low, medium or high)")
        inferred.append((claim.strip(), sure.strip().lower()))
    unknown = [s.strip() for s in (a.unknown or []) if s.strip()]
    if not (seen or measured or decoded):
        die("an analysis starts from what is there: give --seen, --measured or --decoded before any --inferred")
    for what, how in measured:
        if not how:
            die("a measurement says what and how much: \"length=5.4 m, scaled from the number plate\"")
    for what, meaning in decoded:
        if not meaning:
            die("a decoded marking says what it reads and what that means: \"215/65R16C=a load-rated van tyre\"")
    rec("ANALYSIS", a.subject.strip())
    who = a.by or driver()
    rec("SOURCE", (SOURCES[source] % who if "%s" in SOURCES[source] else SOURCES[source]) + (
        "" if source == "sim" else "; examined, not sensed: no instrument of FIRN's was on it"))
    for text in seen:
        rec("SEEN", text)
    for what, how in measured:
        rec("MEASURED", "%s: %s" % (what, how))
    for what, meaning in decoded:
        rec("DECODED", "%s: %s" % (what, meaning))
    for claim, sure in inferred:
        rec("INFERRED", "%s [%s confidence]" % (claim, sure))
    if unknown:
        rec("UNKNOWN", "; ".join(unknown))
    else:
        rec("UNKNOWN", "nothing listed, and there is always something the source does not show: say what")
    if a.next:
        rec("TO SETTLE", "; ".join(x.strip() for x in a.next if x.strip()))
    weak = [c for c, s in inferred if s == "low"]
    rec("RULE", "say it in this order and keep the labels: seen is what is in the picture, measured carries its error, decoded is "
                "read off a marking, inferred is your own reasoning%s" % (
                    " and can be wrong (%d of these at low confidence)" % len(weak) if weak else " and can be wrong"))
    if source in ("photo", "video"):
        more("a face or a number plate is never a way to name a person or find where they live: describe the vehicle, not its owner")


def register(sub):
    p = command(sub, "things", "weigh", cmd_weigh,
                "what a thing weighs and how it behaves: mass from shape, size and material, centre of gravity, tipping, what holds it",
                ["weigh --list", "weigh box 1200x800x600 --material oak", "weigh cylinder 580x880 --wall 1.2 --material steel --fill diesel:80",
                 "weigh cylinder 580x880 --wall 1.2 --material steel --fill water:50 --lying",
                 "weigh box 60x40x180 --unit cm --mass 85 --mu 0.3", "weigh tube 60x3000 --wall 4 --material steel --lying --count 6",
                 "weigh volume 80l --material gravel"])
    p.add_argument("shape", nargs="?", help="box, cylinder, tube, sphere or volume")
    p.add_argument("size", nargs="?", help="box LxWxH (H is up); cylinder DxH; tube DxL; sphere D; volume 80l or 0.5m3")
    p.add_argument("--material", help="what it is made of ('weigh --list')")
    p.add_argument("--density", type=float, help="a density of your own, kg/m3")
    p.add_argument("--mass", type=float, help="its mass in kg, if you know it: then only how it behaves is worked out")
    p.add_argument("--wall", type=float, help="it is hollow: the thickness of its walls")
    p.add_argument("--fill", help="what a hollow thing holds: MATERIAL or MATERIAL:PERCENT, such as water:80")
    p.add_argument("--lying", action="store_true", help="a cylinder or tube on its side")
    p.add_argument("--count", type=int, default=1, help="how many of them (default 1)")
    p.add_argument("--mu", type=float, help="friction between it and the floor, to say whether it slides before it tips")
    p.add_argument("--unit", choices=sorted(UNIT_MM), default="mm", help="unit of every size given (default mm)")
    p.add_argument("--list", action="store_true", help="the materials and their typical densities")

    p = command(sub, "things", "measure", cmd_measure,
                "the real size of something in a picture, scaled from an object of known size in the same picture",
                ["measure --list", "measure --ref card=212 --px wheel=1630", 'measure --ref plate-eu=96 --px length=1010 "roof height=335" --err 3',
                 "measure --ref 2.0m=412 --px opening=265"])
    p.add_argument("--ref", metavar="OBJECT=LENGTH", help="the reference and how long it measures in the picture: card=212, plate-eu=96, 520mm=96")
    p.add_argument("--px", nargs="+", metavar="NAME=LENGTH", help="what to measure, each as it measures in the picture, in the same units")
    p.add_argument("--err", type=float, default=2.0, help="how far out a reading from the picture might be (default 2, in the same units)")
    p.add_argument("--list", action="store_true", help="the objects of standard size that can serve as a reference")

    p = command(sub, "things", "analyse", cmd_analyse,
                "a record of what was made out from a picture or a description: seen, measured, decoded, inferred, unknown",
                ['analyse "white panel van, parked" --seen "roof rack with a ladder" "sliding door on the near side" '
                 '--measured "length=5.4 m, scaled from the number plate" --decoded "215/65R16C=a load-rated van tyre" '
                 '--inferred "long wheelbase, high roof, so likely a 3.5 t van: medium" --unknown "what it carries" "who runs it"',
                 'analyse "warning light on a dashboard" --source description --seen "amber engine outline, steady" '
                 '--inferred "an emissions or engine fault that is not urgent: medium" --next "the fault code, read with a scanner"'])
    p.add_argument("subject", help="what is being looked at, in a few words")
    p.add_argument("--source", default="photo", help="photo (default), video, description, document, or sim")
    p.add_argument("--by", help="who supplied it (default: the driver)")
    p.add_argument("--seen", nargs="+", help="what is plainly there")
    p.add_argument("--measured", nargs="+", metavar="WHAT=HOW MUCH", help="a size or count, and how it was got")
    p.add_argument("--decoded", nargs="+", metavar="MARKING=MEANING", help="a marking read off the thing, and what it means")
    p.add_argument("--inferred", nargs="+", metavar="CLAIM: CONFIDENCE", help="your own reasoning, each ending ': low', ': medium' or ': high'")
    p.add_argument("--unknown", nargs="+", help="what the source does not show")
    p.add_argument("--next", nargs="+", help="what would settle an open point")
