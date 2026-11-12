"""Second Life vehicles: the LSL vehicle reference, a lean script skeleton, and a lint for vehicle scripts.

The reference tables in data/lsl.json were copied from the Second Life wiki and cross-checked against
Linden Lab's own definitions. The skeleton uses only calls and constants from those tables. COMPILED says which
skeletons the maker has compiled in-world, and when: the rest lint clean and say that they are untried.
"""
import math
import re
import sys

from .core import command, die, load_data, more, rec, table, trim

TYPES = ["sled", "car", "boat", "airplane", "balloon"]
COMPILED = dict((kind, "12 November 2026") for kind in TYPES)

_TUNE = {
    "car": [
        ("F", "VEHICLE_LINEAR_MOTOR_TIMESCALE", "1.0"),
        ("F", "VEHICLE_LINEAR_MOTOR_DECAY_TIMESCALE", "1.5"),
        ("F", "VEHICLE_ANGULAR_MOTOR_TIMESCALE", "0.1"),
        ("F", "VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE", "0.5"),
        ("V", "VEHICLE_LINEAR_FRICTION_TIMESCALE", "<1000.0, 2.0, 1000.0>"),
        ("V", "VEHICLE_ANGULAR_FRICTION_TIMESCALE", "<10.0, 10.0, 1000.0>"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_EFFICIENCY", "0.8"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_TIMESCALE", "0.1"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_EFFICIENCY", "0.2"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_TIMESCALE", "0.1"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_EFFICIENCY", "0.5"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_TIMESCALE", "0.5"),
    ],
    "boat": [
        ("F", "VEHICLE_HOVER_HEIGHT", "0.2"),
        ("F", "VEHICLE_HOVER_EFFICIENCY", "0.5"),
        ("F", "VEHICLE_HOVER_TIMESCALE", "1.5"),
        ("F", "VEHICLE_LINEAR_MOTOR_TIMESCALE", "2.0"),
        ("F", "VEHICLE_LINEAR_MOTOR_DECAY_TIMESCALE", "3.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_TIMESCALE", "0.5"),
        ("F", "VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE", "1.0"),
        ("V", "VEHICLE_LINEAR_FRICTION_TIMESCALE", "<10.0, 1.0, 2.0>"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_EFFICIENCY", "0.5"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_TIMESCALE", "2.0"),
    ],
    # the three below are the type's own defaults (lsl.json), written out, except where a comment says otherwise
    "airplane": [
        ("V", "VEHICLE_LINEAR_FRICTION_TIMESCALE", "<200.0, 10.0, 5.0>"),
        ("V", "VEHICLE_ANGULAR_FRICTION_TIMESCALE", "<20.0, 20.0, 20.0>"),
        ("F", "VEHICLE_LINEAR_MOTOR_TIMESCALE", "2.0"),
        ("F", "VEHICLE_LINEAR_MOTOR_DECAY_TIMESCALE", "60.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_TIMESCALE", "4.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE", "8.0"),
        ("F", "VEHICLE_HOVER_TIMESCALE", "1000.0", "300 or more: no hover"),
        ("F", "VEHICLE_BUOYANCY", "0.0"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_EFFICIENCY", "0.5"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_TIMESCALE", "0.5"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_EFFICIENCY", "1.0"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_TIMESCALE", "2.0"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_EFFICIENCY", "0.9"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_TIMESCALE", "2.0"),
        ("F", "VEHICLE_BANKING_EFFICIENCY", "1.0"),
        ("F", "VEHICLE_BANKING_MIX", "0.7"),
        ("F", "VEHICLE_BANKING_TIMESCALE", "2.0"),
    ],
    "balloon": [
        ("V", "VEHICLE_LINEAR_FRICTION_TIMESCALE", "<5.0, 5.0, 5.0>"),
        ("V", "VEHICLE_ANGULAR_FRICTION_TIMESCALE", "<10.0, 10.0, 10.0>"),
        ("F", "VEHICLE_LINEAR_MOTOR_TIMESCALE", "5.0"),
        ("F", "VEHICLE_LINEAR_MOTOR_DECAY_TIMESCALE", "60.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_TIMESCALE", "6.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE", "10.0"),
        ("F", "VEHICLE_HOVER_HEIGHT", "gHeight"),
        ("F", "VEHICLE_HOVER_EFFICIENCY", "0.8"),
        ("F", "VEHICLE_HOVER_TIMESCALE", "10.0"),
        ("F", "VEHICLE_BUOYANCY", "1.0"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_EFFICIENCY", "0.0"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_EFFICIENCY", "0.0"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_EFFICIENCY", "1.0"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_TIMESCALE", "1000.0"),
        ("F", "VEHICLE_BANKING_EFFICIENCY", "0.0"),
    ],
    "sled": [
        ("V", "VEHICLE_LINEAR_FRICTION_TIMESCALE", "SLIDE"),
        ("V", "VEHICLE_ANGULAR_FRICTION_TIMESCALE", "<1000.0, 1000.0, 1000.0>"),
        ("F", "VEHICLE_LINEAR_MOTOR_TIMESCALE", "1000.0", "no motor: gravity moves it"),
        ("F", "VEHICLE_LINEAR_MOTOR_DECAY_TIMESCALE", "120.0"),
        ("F", "VEHICLE_ANGULAR_MOTOR_TIMESCALE", "0.5", "the type's own 1000.0 would be no steering at all"),
        ("F", "VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE", "120.0"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_EFFICIENCY", "1.0"),
        ("F", "VEHICLE_LINEAR_DEFLECTION_TIMESCALE", "1.0"),
        ("F", "VEHICLE_ANGULAR_DEFLECTION_EFFICIENCY", "0.0"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_EFFICIENCY", "1.0"),
        ("F", "VEHICLE_VERTICAL_ATTRACTION_TIMESCALE", "1000.0"),
    ],
}

_DRIVE_CONSTS = """float FWD = {fwd};          // m/s; the engine clamps the linear motor near 30
float REV = {rev};
float TURN = {turn};         // rad/s; the engine caps the angular motor at 4*PI
"""
_STEER = """        if (level & (CONTROL_LEFT | CONTROL_ROT_LEFT)) ang.z = TURN;
        else if (level & (CONTROL_RIGHT | CONTROL_ROT_RIGHT)) ang.z = -TURN;
"""
_DRIVE_CONTROL = """        vector lin;
        vector ang;
        if (level & CONTROL_FWD) lin.x = FWD;
        else if (level & CONTROL_BACK) lin.x = -REV;
""" + _STEER + """        if (lin.x < 0.0) ang.z = -ang.z;
        llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, lin);
        llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, ang);
"""
_ALL_SIX = "CONTROL_FWD | CONTROL_BACK | CONTROL_LEFT | CONTROL_RIGHT | CONTROL_ROT_LEFT | CONTROL_ROT_RIGHT"

# What differs from one type to the next. speed, reverse and turn are the defaults; None means the type has no use for it.
_KINDS = {
    "car": {"verb": "Drive", "speed": 20.0, "reverse": 6.0, "turn": 2.0, "header": "", "consts": _DRIVE_CONSTS, "globals": "",
            "park": "", "mask": _ALL_SIX, "control": _DRIVE_CONTROL},
    "boat": {"verb": "Sail", "speed": 20.0, "reverse": 6.0, "turn": 2.0, "header": "", "consts": _DRIVE_CONSTS, "globals": "",
             "park": "", "mask": _ALL_SIX, "control": _DRIVE_CONTROL},
    "airplane": {
        "verb": "Fly", "speed": 25.0, "reverse": None, "turn": 2.0,
        "header": "// Keys: forward and back pitch the nose down and up, left and right roll, PgUp and PgDn open and close the throttle.\n"
                  "// The settings are the type's own defaults, written out: a place to start, not a tuned aircraft.\n",
        "consts": "float FWD = {fwd};          // m/s at full throttle; the engine clamps the linear motor near 30\n"
                  "float ROLL = {turn};         // rad/s; the engine caps the angular motor at 4*PI\n"
                  "float PITCH = 1.0;        // rad/s\n",
        "globals": "float gThrottle = 0.0;     // 0.0 to 1.0, a quarter for each press\n",
        "park": "    gThrottle = 0.0;\n", "mask": _ALL_SIX + " | CONTROL_UP | CONTROL_DOWN",
        "control": """        vector ang;
        integer pressed = level & edge;
        if (pressed & CONTROL_UP) gThrottle += 0.25;
        if (pressed & CONTROL_DOWN) gThrottle -= 0.25;
        if (gThrottle > 1.0) gThrottle = 1.0;
        if (gThrottle < 0.0) gThrottle = 0.0;
        if (level & CONTROL_FWD) ang.y = PITCH;
        else if (level & CONTROL_BACK) ang.y = -PITCH;
        if (level & (CONTROL_LEFT | CONTROL_ROT_LEFT)) ang.x = -ROLL;
        else if (level & (CONTROL_RIGHT | CONTROL_ROT_RIGHT)) ang.x = ROLL;
        llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, <FWD * gThrottle, 0.0, 0.0>);
        llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, ang);
"""},
    "balloon": {
        "verb": "Fly", "speed": 4.0, "reverse": 2.0, "turn": 0.5,
        "header": "// Keys: forward, back and turn; PgUp and PgDn raise and lower the height it hovers at.\n"
                  "// The settings are the type's own defaults, written out: a place to start, not a tuned balloon.\n",
        "consts": _DRIVE_CONSTS + "float STEP = 2.0;         // m of height for each press\n",
        "globals": "float gHeight = 5.0;       // m above the ground or the water\n",
        "park": "", "mask": _ALL_SIX + " | CONTROL_UP | CONTROL_DOWN",
        "control": """        vector lin;
        vector ang;
        integer pressed = level & edge;
        if (pressed & CONTROL_UP) gHeight += STEP;
        if (pressed & CONTROL_DOWN) gHeight -= STEP;
        if (gHeight < 1.0) gHeight = 1.0;
        if (gHeight > 100.0) gHeight = 100.0;
        if (pressed & (CONTROL_UP | CONTROL_DOWN)) llSetVehicleFloatParam(VEHICLE_HOVER_HEIGHT, gHeight);
        if (level & CONTROL_FWD) lin.x = FWD;
        else if (level & CONTROL_BACK) lin.x = -REV;
""" + _STEER + """        llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, lin);
        llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, ang);
"""},
    "sled": {
        "verb": "Ride", "speed": None, "reverse": None, "turn": 1.0,
        "header": "// Keys: left and right steer, back brakes. It has no motor: gravity moves it.\n"
                  "// The settings are the type's own defaults, written out, but for the steering: a place to start.\n",
        "consts": "float TURN = {turn};         // rad/s; the engine caps the angular motor at 4*PI\n"
                  "vector SLIDE = <30.0, 1.0, 1000.0>;\n"
                  "vector BRAKE = <2.0, 1.0, 1000.0>;    // friction while the back key is held\n",
        "globals": "integer gBraking = FALSE;\n",
        "park": "    llSetVehicleVectorParam(VEHICLE_LINEAR_FRICTION_TIMESCALE, SLIDE);\n    gBraking = FALSE;\n",
        "mask": "CONTROL_BACK | CONTROL_LEFT | CONTROL_RIGHT | CONTROL_ROT_LEFT | CONTROL_ROT_RIGHT",
        "control": """        vector ang;
        integer brake = level & CONTROL_BACK;
        if (brake && !gBraking)
        {
            llSetVehicleVectorParam(VEHICLE_LINEAR_FRICTION_TIMESCALE, BRAKE);
            gBraking = TRUE;
        }
        else if (!brake && gBraking)
        {
            llSetVehicleVectorParam(VEHICLE_LINEAR_FRICTION_TIMESCALE, SLIDE);
            gBraking = FALSE;
        }
""" + _STEER + """        llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, ang);
"""},
}

_SKELETON = """// Vehicle core: {kind}. Forward is the root prim's local +X, left is +Y, up is +Z.
// If the build faces another way, set VEHICLE_REFERENCE_FRAME rather than re-rotating prims.
{header}{consts}vector SIT = <{sit}>;
string ANIM = "{anim}";            // an animation in this prim's inventory; "" keeps the default sit

key gPilot = NULL_KEY;
{globals}
tune()
{{
    llSetVehicleType({vtype});
{tune}
}}
{camera_fn}
park()
{{
    llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, ZERO_VECTOR);
    llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, ZERO_VECTOR);
{park}    llSetStatus(STATUS_PHYSICS, FALSE);
}}

default
{{
    state_entry()
    {{
        llSetStatus(STATUS_PHYSICS, FALSE);
        llSitTarget(SIT, ZERO_ROTATION);
        llSetSitText("{verb}");
        tune();
    }}

    on_rez(integer n)
    {{
        llResetScript();
    }}

    changed(integer c)
    {{
        if (c & CHANGED_LINK)
        {{
            key who = llAvatarOnSitTarget();
            if (who != NULL_KEY && gPilot == NULL_KEY)
            {{
                gPilot = who;
                llRequestPermissions(who, {perms});
            }}
            else if (who == NULL_KEY && gPilot != NULL_KEY)
            {{
                park();
                if (llGetPermissionsKey() == gPilot)
                {{
                    integer p = llGetPermissions();
                    if ((p & PERMISSION_TRIGGER_ANIMATION) && ANIM != "") llStopAnimation(ANIM);
                    if (p & PERMISSION_TAKE_CONTROLS) llReleaseControls();
                }}
                gPilot = NULL_KEY;
            }}
        }}
        if ((c & CHANGED_REGION) && gPilot != NULL_KEY && llGetPermissionsKey() == gPilot)
        {{
            // After a crossing: common practice, not Linden guidance.
            integer p = llGetPermissions();
{region_camera}            if ((p & PERMISSION_TRIGGER_ANIMATION) && ANIM != "") llStartAnimation(ANIM);
        }}
    }}

    run_time_permissions(integer p)
    {{
        if ((p & PERMISSION_TRIGGER_ANIMATION) && ANIM != "")
        {{
            llStopAnimation("sit");
            llStartAnimation(ANIM);
        }}
{perm_camera}        if (p & PERMISSION_TAKE_CONTROLS)
        {{
            llTakeControls({mask}, TRUE, FALSE);
            llSetStatus(STATUS_PHYSICS, TRUE);
        }}
    }}

    control(key id, integer level, integer edge)
    {{
{control}    }}
}}
"""

_CAMERA_FN = """
camera()
{
    llSetCameraParams([
        CAMERA_ACTIVE, TRUE,
        CAMERA_BEHINDNESS_ANGLE, 10.0,
        CAMERA_BEHINDNESS_LAG, 0.3,
        CAMERA_DISTANCE, 7.0,
        CAMERA_PITCH, 12.0,
        CAMERA_FOCUS_LAG, 0.05,
        CAMERA_FOCUS_OFFSET, <2.0, 0.0, 0.5>,
        CAMERA_POSITION_LAG, 0.2
    ]);
}
"""


def _f(x):
    s = trim(x, 3)
    return s if "." in s else s + ".0"


def skeleton(kind, fwd, rev, turn, sit, anim, camera):
    """The script for one vehicle type. fwd, rev and turn may be None: the type's own default is used."""
    if kind not in _KINDS:
        die("a skeleton exists for: %s" % ", ".join(TYPES))
    k = _KINDS[kind]
    for flag, value, key in (("--speed", fwd, "speed"), ("--reverse", rev, "reverse")):
        if value is not None and k[key] is None:
            die("%s does not apply to a %s: it has no %s" % (flag, kind, "motor" if kind == "sled" else "reverse"))
    fwd = k["speed"] or 0.0 if fwd is None else fwd
    rev = k["reverse"] or 0.0 if rev is None else rev
    turn = k["turn"] if turn is None else turn
    if (k["speed"] is not None and not 0 < fwd <= 30) or not 0 <= rev <= 30:
        die("speeds are in m/s, up to 30: the engine clamps the linear motor there")
    if not 0 < turn <= 12.56:
        die("turn rate is in rad/s, up to 4*PI (12.56)")
    try:
        sx, sy, sz = [float(v) for v in sit.split(",")]
    except ValueError:
        die("--sit is three numbers: x,y,z in metres from the root prim")
    if sx == 0 and sy == 0 and sz == 0:
        die("a sit target of 0,0,0 removes the sit target: move it a little")
    if '"' in anim or "\\" in anim:
        die("the animation name cannot contain quotes or backslashes")
    lines = []
    for row in _TUNE[kind]:
        fn = "llSetVehicleFloatParam" if row[0] == "F" else "llSetVehicleVectorParam"
        lines.append("    %s(%s, %s);%s" % (fn, row[1], row[2], "    // " + row[3] if len(row) > 3 else ""))
    perms = "PERMISSION_TAKE_CONTROLS | PERMISSION_TRIGGER_ANIMATION"
    if camera:
        perms += " | PERMISSION_CONTROL_CAMERA"
    return _SKELETON.format(
        kind=kind, sit="%s, %s, %s" % (_f(sx), _f(sy), _f(sz)), anim=anim, header=k["header"],
        consts=k["consts"].format(fwd=_f(fwd), rev=_f(rev), turn=_f(turn)), globals=k["globals"], park=k["park"],
        mask=k["mask"], control=k["control"],
        vtype="VEHICLE_TYPE_" + kind.upper(), tune="\n".join(lines), verb=k["verb"],
        perms=perms, camera_fn=_CAMERA_FN if camera else "",
        region_camera="            if (p & PERMISSION_CONTROL_CAMERA) camera();\n" if camera else "",
        perm_camera="        if (p & PERMISSION_CONTROL_CAMERA) camera();\n" if camera else "")


# ---- lint

def _strip(src):
    """Blank out comments and string contents, keeping every line break and column."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
        elif c == '"':
            out.append('"')
            i += 1
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append('"')
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _event_body(code, name):
    """(start offset, text) of an event's body, or None."""
    m = re.search(r"\b%s\s*\([^)]*\)\s*\{" % name, code)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(code) and depth:
        depth += {"{": 1, "}": -1}.get(code[i], 0)
        i += 1
    return m.end(), code[m.end():i]


def lint(src):
    """List of (line, level, text). Heuristic: it reads the text, it does not compile it."""
    from . import desk
    data = load_data("lsl")
    found = []
    for ln, col, ch, what, repl in desk.check_text(src, code=True):
        found.append((ln, "WARN", "col %d: %s U+%04X (plain ASCII only in scripts)" % (col, what, ord(ch))))
    code = _strip(src)

    def line_of(pos):
        return code.count("\n", 0, pos) + 1

    for open_, close in (("{", "}"), ("(", ")"), ("[", "]")):
        if code.count(open_) != code.count(close):
            found.append((0, "WARN", "unbalanced %s %s: %d against %d" % (open_, close, code.count(open_), code.count(close))))
    if not re.search(r"\bdefault\s*\{", code):
        found.append((0, "WARN", "no default state"))
    known = set(data["types"] and ["VEHICLE_TYPE_" + t.upper() for t in data["types"]])
    known |= set(r[0] for r in data["float_params"]) | set(r[0] for r in data["vector_params"]) | set(r[0] for r in data["flags"])
    known |= set(r[0] for r in data["controls"]) | set(r[0] for r in data["camera"])
    soft = set(r[0] for r in data["permissions"]) | set(data["changed"]) | set(data["status"])
    for m in re.finditer(r"\b(VEHICLE|CONTROL|CAMERA|PERMISSION|CHANGED|STATUS)_[A-Z0-9_]+\b", code):
        name = m.group(0)
        if name in data["deprecated"]:
            found.append((line_of(m.start()), "NOTE", "%s is deprecated: use %s" % (name, data["deprecated"][name])))
        elif m.group(1) in ("VEHICLE", "CONTROL", "CAMERA") and name not in known:
            found.append((line_of(m.start()), "WARN", "%s is not an LSL constant (not in the checked tables)" % name))
        elif m.group(1) in ("PERMISSION", "CHANGED", "STATUS") and name not in soft:
            found.append((line_of(m.start()), "NOTE", "%s is not in FIRN's table: check it against the wiki" % name))
    for m in re.finditer(r"[)\]>]\s*\.\s*([xyzs])\b", code):
        found.append((line_of(m.start()), "WARN", "'.%s' on an expression: LSL reads a member only from a variable, so this will "
                      "not compile. Put the value in a variable first" % m.group(1)))
    vehicle = "llSetVehicleType" in code
    if "llTakeControls" in code and not re.search(r"\brun_time_permissions\s*\(", code):
        found.append((0, "WARN", "llTakeControls without a run_time_permissions event: take controls there, not on trust"))
    if vehicle and not re.search(r"STATUS_PHYSICS\s*,\s*TRUE", code):
        found.append((0, "WARN", "the vehicle type is set but nothing turns STATUS_PHYSICS on: it will not move"))
    if vehicle:
        for fn in ("llSetBuoyancy", "llSetForce", "llSetTorque", "llSetHoverHeight", "llGroundRepel"):
            for m in re.finditer(r"\b%s\s*\(" % fn, code):
                found.append((line_of(m.start()), "WARN", "%s fights the vehicle engine: the wiki says not to mix them" % fn))
    if re.search(r"STATUS_PHYSICS\s*,\s*TRUE", code):
        for fn in ("llSetPos", "llSetRot"):
            for m in re.finditer(r"\b%s\s*\(" % fn, code):
                found.append((line_of(m.start()), "NOTE", "%s does nothing to a physical root prim and costs 0.2 s" % fn))
    body = _event_body(code, "control")
    if body:
        start, text = body
        for fn, why in (("llSleep", "sleeping in control() stalls the queue (64 events, then they are dropped)"),
                        ("llOwnerSay", "chat in control() floods: it fires many times a second"),
                        ("llSay", "chat in control() floods: it fires many times a second"),
                        ("llWhisper", "chat in control() floods"), ("llShout", "chat in control() floods"),
                        ("llSetText", "llSetText in control() is costly"),
                        ("llSetPrimitiveParams", "0.2 s forced delay inside control(): use llSetLinkPrimitiveParamsFast"),
                        ("llSetLinkPrimitiveParams", "0.2 s forced delay inside control(): use llSetLinkPrimitiveParamsFast")):
            for m in re.finditer(r"\b%s\s*\(" % fn, text):
                found.append((line_of(start + m.start()), "WARN", why))
    if "llSitTarget" in code:
        for m in re.finditer(r"llRequestPermissions\s*\(\s*llGetOwner\s*\(", code):
            found.append((line_of(m.start()), "NOTE", "permissions asked of the owner: a vehicle needs them from whoever sits down"))
    asks = list(re.finditer(r"\bllRequestPermissions\s*\(", code))
    if len(asks) > 1:
        found.append((line_of(asks[1].start()), "NOTE", "permissions do not accumulate: ask for all of them in one call, OR-ed together"))
    for name, cap, unit in (("VEHICLE_LINEAR_MOTOR_DIRECTION", 30.0, "m/s"), ("VEHICLE_ANGULAR_MOTOR_DIRECTION", 12.57, "rad/s")):
        for m in re.finditer(r"%s\s*,\s*<\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*>" % name, code):
            if any(abs(float(v)) > cap for v in m.groups()):
                found.append((line_of(m.start()), "NOTE", "%s past %s %s is clamped by the engine" % (name, trim(cap, 2), unit)))
    for m in re.finditer(r"llSetTimerEvent\s*\(\s*(0?\.\d+)\s*\)", code):
        if float(m.group(1)) < 0.1:
            found.append((line_of(m.start()), "NOTE", "a %s s timer runs every frame or two: that is script time on every tick" % m.group(1)))
    found.sort(key=lambda f: (f[0], f[1]))
    return found


MOTOR_CAP = 30.0
FRICTION_FLOOR = 0.07
YAW_CAP = 4 * math.pi


def _f(x):
    """A number as an LSL float literal: always with a decimal point."""
    s = trim(x, 2)
    return s if "." in s else s + ".0"


def tune(a):
    """Starting values for a ground vehicle from the figures of a real car.

    The model is the one the wiki's parameter table describes: speed closes on the linear motor's target with the
    motor timescale, and falls away with the friction timescale. With both at work, dv/dt = (target - v) / tm - v / tf,
    so the speed settles at target * tf / (tm + tf) and closes on it with the timescale tm * tf / (tm + tf)."""
    if a.top is None:
        die("lsl tune needs the top speed you want: --top 100 (km/h), and --reach 80 --in 5 for the acceleration")
    if a.top <= 0 or a.coast <= FRICTION_FLOOR:
        die("--top must be above zero and --coast above %s s" % trim(FRICTION_FLOOR, 2))
    v_top = a.top / 3.6
    notes = []
    if v_top > MOTOR_CAP:
        notes.append("%s km/h is %s m/s, past the engine's linear motor limit of about %s m/s (%s km/h): the figures below are for %s km/h"
                     % (trim(a.top, 0), trim(v_top, 1), trim(MOTOR_CAP, 0), trim(MOTOR_CAP * 3.6, 0), trim(MOTOR_CAP * 3.6, 0)))
        v_top = MOTOR_CAP
    tf = a.coast
    tm = 1.0
    how = "the car type's default"
    if a.reach is not None or a.within is not None:
        if a.reach is None or a.within is None or a.within <= 0:
            die("acceleration is a pair: --reach 80 --in 5 (reach 80 km/h in 5 s)")
        v_ref = a.reach / 3.6
        if not 0 < v_ref < v_top:
            die("--reach must be below the top speed (%s km/h): a speed is approached, never passed" % trim(v_top * 3.6, 0))
        t_eff = a.within / -math.log(1.0 - v_ref / v_top)
        if t_eff >= tf:
            die("to coast for %s s and still reach %s km/h in %s s cannot both hold: lengthen --coast above %s s" % (
                trim(tf, 1), trim(a.reach, 0), trim(a.within, 1), trim(t_eff, 1)))
        tm = t_eff * tf / (tf - t_eff)
        how = "reaches %s km/h in %s s" % (trim(a.reach, 0), trim(a.within, 1))
    target = v_top * (tm + tf) / tf
    if target > MOTOR_CAP:
        reached = MOTOR_CAP * tf / (tm + tf)
        notes.append("the motor target is held at the engine limit, so the speed settles near %s km/h, not %s: lengthen --coast to close the gap"
                     % (trim(reached * 3.6, 0), trim(v_top * 3.6, 0)))
        target = MOTOR_CAP
    rec("TARGETS", "top %s km/h (%s m/s)%s; lift off and the speed falls to about a third in %s s [as given]" % (
        trim(v_top * 3.6, 0), trim(v_top, 1), "; %s" % how if a.reach is not None else "", trim(tf, 1)))
    rec("MOTOR", "llSetVehicleFloatParam(VEHICLE_LINEAR_MOTOR_TIMESCALE, %s);  // %s" % (_f(tm), how))
    more("llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, <%s, 0.0, 0.0>);  // while forward is held; a little above "
         "the top speed, to make up for friction" % _f(target))
    rec("FRICTION", "llSetVehicleVectorParam(VEHICLE_LINEAR_FRICTION_TIMESCALE, <%s, 2.0, 1000.0>);  // x is the coast; y and z "
                    "are the car type's defaults" % _f(tf))
    if a.brake_from is not None or a.brake_m is not None:
        if a.brake_from is None or a.brake_m is None or a.brake_from <= 0 or a.brake_m <= 0:
            die("braking is a pair: --brake-from 100 --brake-m 40 (stop from 100 km/h in 40 m)")
        tb = a.brake_m / (a.brake_from / 3.6)
        line = "llSetVehicleVectorParam(VEHICLE_LINEAR_FRICTION_TIMESCALE, <%s, 2.0, 1000.0>);  // while the brake is held: " \
               "from %s km/h it runs on about %s m" % (_f(max(tb, FRICTION_FLOOR)), trim(a.brake_from, 0), trim(a.brake_m, 0))
        rec("BRAKE", line)
        more("set the motor direction to ZERO_VECTOR at the same moment, and put the coast value back when the brake is released")
        if tb < FRICTION_FLOOR:
            notes.append("that braking distance needs a friction timescale under the %s s floor: the vehicle will take longer" % trim(FRICTION_FLOOR, 2))
    if a.turn_radius is not None:
        if a.turn_radius <= 0 or a.at <= 0:
            die("turning is --turn-radius 6 --at 30 (a 6 m radius at 30 km/h)")
        yaw = (a.at / 3.6) / a.turn_radius
        if yaw > YAW_CAP:
            notes.append("that turn needs %s rad/s, past the engine's %s rad/s: it will be wider" % (trim(yaw, 2), trim(YAW_CAP, 2)))
            yaw = YAW_CAP
        rec("TURN", "llSetVehicleVectorParam(VEHICLE_ANGULAR_MOTOR_DIRECTION, <0.0, 0.0, %s>);  // left; negative for right: a %s m "
                    "radius at %s km/h" % (_f(yaw), trim(a.turn_radius, 1), trim(a.at, 0)))
        more("for a turn that widens with speed, as a real car's does, set z to speed / radius each time, capped at this value")
    for n in notes:
        rec("LIMIT", n)
    rec("MODEL", "speed closes on the motor's target with the motor timescale and falls away with the friction timescale, as "
                 "the wiki's parameter table describes them [derived]")
    rec("NEXT", "these are starting values: the physics engine adds slopes, collisions and its own damping, so tune from them "
                "by driving. Region crossings are a separate matter: 'lsl caveats'")


def cmd_lsl(a):
    data = load_data("lsl")
    what = a.what
    if what == "defaults":
        types = [a.type] if a.type else TYPES
        for t in types:
            if t not in TYPES:
                die("type is one of: %s" % ", ".join(TYPES))
        rows = []
        for name, vals in data["defaults"].items():
            rows.append([name] + [vals[t] for t in types])
        table(rows, header=["set by llSetVehicleType"] + [t.upper() for t in types], indent=2)
        frows = [[name] + ["set" if vals[t] else "cleared" for t in types] for name, vals in data["flag_defaults"].items()]
        table(frows, header=["flag"] + [t.upper() for t in types], indent=2)
        for t in types:
            rec(t.upper(), data["type_notes"][t])
        rec("WARNING", data["warning"])
        rec("SOURCE", "wiki.secondlife.com/wiki/LlSetVehicleType and the VEHICLE_TYPE pages [checked 2026-11-10]")
        return
    if what == "params":
        want = (a.find or "").lower()
        rows = [(n, str(v), m, lim) for n, v, m, lim in data["float_params"] + data["vector_params"]
                if want in n.lower() or want in m.lower()]
        if not rows:
            rec("NONE", "no vehicle parameter matches '%s'" % a.find)
            return
        table(rows, header=("parameter", "value", "what it does", "limit"), indent=2)
        rec("SET WITH", "llSetVehicleFloatParam for the single numbers, llSetVehicleVectorParam for the vectors (a float sets "
                        "all three axes alike), llSetVehicleRotationParam for the reference frame [checked 2026-11-10]")
        return
    if what == "flags":
        table([(n, v, m) for n, v, m in data["flags"]], header=("flag", "value", "what it does"), indent=2)
        rec("SET WITH", "llSetVehicleFlags and llRemoveVehicleFlags; some flags survive a script reset, so remove the ones you do not want")
        return
    if what in ("limits", "caveats"):
        for line in data[what]:
            rec(what.upper()[:-1], line)
        if what == "limits":
            for line in data["disputes"]:
                rec("UNSETTLED", line)
        return
    if what == "controls":
        table([(n, v, m) for n, v, m in data["controls"]], header=("control", "value", "key"), indent=2)
        for line in data["control_event"]:
            rec("EVENT", line)
        return
    if what == "camera":
        table([(n, str(v), t, r, d) for n, v, t, r, d in data["camera"]], header=("rule", "value", "type", "range", "default"), indent=2)
        rec("NOTE", "needs PERMISSION_CONTROL_CAMERA; cleared automatically when the avatar stands; no effect in mouselook")
        return
    if what == "skeleton":
        kind = a.type or "car"
        print(skeleton(kind, a.speed, a.reverse, a.turn, a.sit, a.anim or "", not a.no_camera), end="")
        if kind not in COMPILED:
            sys.stderr.write("%-10s the %s skeleton lints clean but has not been compiled in-world yet: say so when you hand it "
                             "over, and try it in a sandbox region first\n" % ("NOTE", kind))
        return
    if what == "tune":
        tune(a)
        return
    # lint
    if not a.file:
        die("lint needs a script file: lsl lint vehicle.lsl")
    try:
        with open(a.file, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        die("cannot read %s: %s" % (a.file, e.strerror or e))
    except UnicodeDecodeError:
        die("%s is not UTF-8 text" % a.file)
    found = lint(src)
    for ln, level, text in found:
        rec("%s %s" % (level, "L%d" % ln if ln else "file"), text)
    warns = sum(1 for f in found if f[1] == "WARN")
    rec("LINT", "%d warning%s, %d note%s in %d lines [heuristic: it reads the text, it does not compile it]" % (
        warns, "" if warns == 1 else "s", len(found) - warns, "" if len(found) - warns == 1 else "s", len(src.splitlines())))
    if warns:
        raise SystemExit(1)


def register(sub):
    p = command(sub, "sl", "lsl", cmd_lsl,
                "Second Life vehicles: type defaults, parameters, flags, limits, caveats, a lean script skeleton for each type, and a lint",
                ["lsl defaults --type car", "lsl params --find hover", "lsl flags", "lsl limits", "lsl caveats", "lsl controls",
                 "lsl camera", "lsl skeleton --type car --speed 22 --turn 2.2", "lsl skeleton --type airplane", "lsl lint vehicle.lsl",
                 "lsl tune --top 100 --reach 80 --in 5 --brake-from 100 --brake-m 40 --turn-radius 6 --at 30"])
    p.add_argument("what", choices=["defaults", "params", "flags", "limits", "caveats", "controls", "camera", "skeleton", "lint", "tune"])
    p.add_argument("file", nargs="?", help="lint: the script to read")
    p.add_argument("--type", help="defaults and skeleton: sled, car, boat, airplane or balloon (skeleton: default car)")
    p.add_argument("--find", help="params: text to look for")
    p.add_argument("--speed", type=float, help="skeleton: forward speed, m/s (car and boat 20, airplane 25, balloon 4; engine limit about 30)")
    p.add_argument("--reverse", type=float, help="skeleton: reverse speed, m/s (car and boat 6, balloon 2)")
    p.add_argument("--turn", type=float, help="skeleton: turn rate, rad/s; an airplane's roll rate (car, boat and airplane 2, sled 1, balloon 0.5)")
    p.add_argument("--sit", default="0.3,0.0,0.5", help="skeleton: sit target x,y,z in metres (default 0.3,0.0,0.5)")
    p.add_argument("--anim", help="skeleton: driving animation name in the root prim's inventory")
    p.add_argument("--no-camera", action="store_true", help="skeleton: leave the follow camera out")
    p.add_argument("--top", type=float, help="tune: top speed wanted, km/h")
    p.add_argument("--reach", type=float, help="tune: a speed to reach, km/h ...")
    p.add_argument("--in", dest="within", type=float, help="tune: ... in this many seconds")
    p.add_argument("--coast", type=float, default=100.0, help="tune: seconds for the speed to fall to about a third off the throttle (default 100)")
    p.add_argument("--brake-from", type=float, help="tune: braking from this speed, km/h ...")
    p.add_argument("--brake-m", type=float, help="tune: ... in this many metres")
    p.add_argument("--turn-radius", type=float, help="tune: turning radius wanted, m ...")
    p.add_argument("--at", type=float, default=30.0, help="tune: ... at this speed, km/h (default 30)")
