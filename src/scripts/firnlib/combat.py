"""Wargame arithmetic: force ratios, time to kill, scenario briefs.

Everything here is game and model maths. Game values are never built in: pass them in
from the current patch or rulebook. Nothing here describes real weapons.
"""
import math
import random

from .core import command, die, driver, fmt_dur, load_data, more, num, rec, table, trim
from .dice import make_rng, pct


# ---- Lanchester force-ratio models

def _lanchester_rates(law, b, r, blue_rate, red_rate):
    """(blue losses per unit time, red losses per unit time)."""
    if law == "square":
        return red_rate * r, blue_rate * b
    return red_rate * r * b, blue_rate * b * r


def cmd_lanchester(a):
    b0, r0 = float(a.blue), float(a.red)
    if b0 <= 0 or r0 <= 0 or a.blue_rate <= 0 or a.red_rate <= 0:
        die("forces and rates must be positive")
    if not (0 <= a.blue_break < 100 and 0 <= a.red_break < 100):
        die("break points are percentages from 0 to 99")
    if a.step <= 0:
        die("--step must be positive")
    b_stop = b0 * a.blue_break / 100.0
    r_stop = r0 * a.red_break / 100.0
    breaks = a.blue_break > 0 or a.red_break > 0
    rec("MODEL", "%s law: %s" % (a.law, "aimed fire, losses scale with the enemy's numbers" if a.law == "square"
                                 else "area fire, losses scale with both sides' numbers"))
    if a.law == "square":
        bs, rs = a.blue_rate * b0 * b0, a.red_rate * r0 * r0
        surv = math.sqrt(abs(bs - rs) / (a.blue_rate if bs > rs else a.red_rate))
    else:
        bs, rs = a.blue_rate * b0, a.red_rate * r0
        surv = abs(bs - rs) / (a.blue_rate if bs > rs else a.red_rate)
    if not breaks:
        if abs(bs - rs) < 1e-9:
            rec("RESULT", "mutual destruction [model, fought to the end]")
        else:
            rec("RESULT", "%s wins with ~%s of %s left [model, fought to the end]" % (
                "BLUE" if bs > rs else "RED", trim(surv, 1), trim(b0 if bs > rs else r0, 1)))
        rec("STRENGTH", "blue %s vs red %s (%s); the larger side wins" % (
            num(bs, 1), num(rs, 1), "rate x force squared" if a.law == "square" else "rate x force"))

    b, r, t, dt = b0, r0, 0.0, a.step
    floor_b = b_stop if a.blue_break > 0 else 0.5
    floor_r = r_stop if a.red_break > 0 else 0.5
    trace = [(0.0, b0, r0)]
    while b > floor_b and r > floor_r and t < a.max_time:
        lb, lr = _lanchester_rates(a.law, b, r, a.blue_rate, a.red_rate)
        b, r, t = max(0.0, b - lb * dt), max(0.0, r - lr * dt), t + dt
        trace.append((t, b, r))

    def left(x, floor, broke):
        if x > floor:
            return trim(x, 1)
        return "%s (broke off)" % trim(x, 1) if broke else "0 (gone)"

    if t >= a.max_time:
        rec("SIM", "t=%s still fighting: blue %s red %s (raise --max-time)" % (trim(t, 2), trim(b, 1), trim(r, 1)))
    else:
        rec("SIM", "t=%s blue %s | red %s" % (trim(t, 2), left(b, floor_b, a.blue_break > 0), left(r, floor_r, a.red_break > 0)))
    if breaks:
        winner = "BLUE" if r <= floor_r and b > floor_b else "RED" if b <= floor_b and r > floor_r else "neither side"
        rec("RESULT", "%s holds the field [model, break points: blue %s%%, red %s%%]" % (
            winner, trim(a.blue_break, 1), trim(a.red_break, 1)))
    if a.trace:
        rows = []
        n = max(2, a.trace)
        for i in range(n):
            tt, bb, rr = trace[min(len(trace) - 1, int(round(i * (len(trace) - 1) / float(n - 1))))]
            rows.append((trim(tt, 2), trim(bb, 1), trim(rr, 1)))
        table(rows, header=("t", "blue", "red"), indent=2, right=(0, 1, 2))
    if a.runs:
        if not 1 <= a.runs <= 20000:
            die("--runs must be 1 to 20000")
        rng = make_rng(a.seed)
        bi, ri = int(round(b0)), int(round(r0))
        wins = {"blue": 0, "red": 0, "none": 0}
        keep, times = [], []
        for _ in range(a.runs):
            b, r, t = bi, ri, 0.0
            while b > b_stop and r > r_stop and b > 0 and r > 0:
                lb, lr = _lanchester_rates(a.law, b, r, a.blue_rate, a.red_rate)
                total = lb + lr
                t += rng.expovariate(total)
                if rng.random() < lr / total:
                    r -= 1
                else:
                    b -= 1
            blue_out = b <= b_stop or b <= 0
            red_out = r <= r_stop or r <= 0
            side = "none" if blue_out and red_out else "red" if blue_out else "blue"
            wins[side] += 1
            keep.append(b if side == "blue" else r)
            times.append(t)
        keep.sort()
        lo, hi = keep[int(0.05 * (len(keep) - 1))], keep[int(0.95 * (len(keep) - 1))]
        rec("ODDS", "blue holds %s | red holds %s over %d runs of whole units [simulated%s]" % (
            pct(wins["blue"] / float(a.runs)), pct(wins["red"] / float(a.runs)), a.runs,
            ", seed %d" % a.seed if a.seed is not None else ""))
        more("the side left standing keeps %s on average (5-95%%: %d to %d); mean duration t=%s" % (
            trim(sum(keep) / float(len(keep)), 1), lo, hi, trim(sum(times) / len(times), 2)))
    rec("NOTE", "a classic model, not a prediction; terrain, morale and surprise are not in it")


# ---- time to kill

def _frac(x, what):
    if x is None:
        return 1.0
    v = x / 100.0 if x > 1 else x
    if not 0 < v <= 1:
        die("%s must be a chance: 0-1 or 1-100 percent" % what)
    return v


def _shot_times(count, reload, clip, intra, first):
    """Times of the first `count` shots. A clip gun fires its clip `intra` apart, then reloads."""
    out, t = [], first
    for i in range(count):
        out.append(t)
        if clip and clip > 1:
            t += intra if (i + 1) % clip else reload
        else:
            t += reload
    return out


def _sim_kill(hp, dmg, reload, clip, intra, first, hit, pen, spread, rng, cap=400):
    """One randomised engagement: time at which hp reaches zero."""
    t, shots, left = first, 0, hp
    while shots < cap:
        shots += 1
        if rng.random() < hit and rng.random() < pen:
            left -= dmg * (1.0 + spread * (2.0 * rng.random() - 1.0))
            if left <= 0:
                return t, shots
        if clip and clip > 1:
            t += intra if shots % clip else reload
        else:
            t += reload
    return float("inf"), shots


def cmd_ttk(a):
    for name in ("hp", "dmg", "reload"):
        if getattr(a, name) <= 0:
            die("--%s must be positive" % name)
    hit, pen = _frac(a.hit, "--hit"), _frac(a.pen, "--pen")
    spread = (a.rng or 0.0) / 100.0
    if not 0 <= spread < 1:
        die("--rng is a percentage spread, 0 to 99")
    clip = a.clip or 1
    intra = a.intra if a.intra is not None else a.reload
    if clip > 1:
        cycle = a.reload + (clip - 1) * intra
        dpm = a.dmg * clip * 60.0 / cycle
        gun = "%s dmg x %d, %s s apart, then %s s reload" % (trim(a.dmg, 1), clip, trim(intra, 2), trim(a.reload, 2))
    else:
        dpm = a.dmg * 60.0 / a.reload
        gun = "%s dmg every %s s" % (trim(a.dmg, 1), trim(a.reload, 2))
    rec("GUN", "%s -> %s DPM [derived]" % (gun, num(dpm)))
    if hit < 1 or pen < 1:
        more("effective %s DPM at %s hit x %s pen" % (num(dpm * hit * pen), pct(hit), pct(pen)))
    need = int(math.ceil(a.hp / a.dmg - 1e-9))
    best = int(math.ceil(a.hp / (a.dmg * (1 + spread)) - 1e-9))
    worst = int(math.ceil(a.hp / (a.dmg * (1 - spread)) - 1e-9)) if spread else need
    span = "" if not spread else " (%d with every roll high, %d with every roll low)" % (best, worst)
    rec("TARGET", "%s HP -> %d damaging shot%s at average damage%s" % (num(a.hp), need, "" if need == 1 else "s", span))
    times = _shot_times(need, a.reload, clip, intra, a.first)
    rec("TTK", "%s if every shot hits, pens and rolls average [derived]" % fmt_dur(times[-1]))
    runs = a.runs
    randomised = hit < 1 or pen < 1 or spread > 0
    rng = make_rng(a.seed)
    if randomised:
        res = sorted(_sim_kill(a.hp, a.dmg, a.reload, clip, intra, a.first, hit, pen, spread, rng)[0] for _ in range(runs))
        fin = [x for x in res if x != float("inf")]
        if fin:
            more("with chance in it: median %s, mean %s, 90%% of runs within %s [simulated, %d runs%s]" % (
                fmt_dur(fin[len(fin) // 2]), fmt_dur(sum(fin) / len(fin)), fmt_dur(fin[min(len(fin) - 1, int(0.9 * len(fin)))]),
                runs, ", seed %d" % a.seed if a.seed is not None else ""))
    if a.hp_self or a.vs_dmg or a.vs_reload:
        if not (a.hp_self and a.vs_dmg and a.vs_reload) or min(a.hp_self, a.vs_dmg, a.vs_reload) <= 0:
            die("a duel needs --hp-self (your hit points), --vs-dmg and --vs-reload (their gun), all positive")
        v_hit, v_pen = _frac(a.vs_hit, "--vs-hit"), _frac(a.vs_pen, "--vs-pen")
        v_clip = a.vs_clip or 1
        v_intra = a.vs_intra if a.vs_intra is not None else a.vs_reload
        v_first = a.vs_first
        mine = times[-1]
        v_need = int(math.ceil(a.hp_self / a.vs_dmg - 1e-9))
        theirs = _shot_times(v_need, a.vs_reload, v_clip, v_intra, v_first)[-1]
        rec("DUEL", "you need %s, they need %s -> %s [derived, every shot counting]" % (
            fmt_dur(mine), fmt_dur(theirs), "you win the trade by %s" % fmt_dur(theirs - mine) if mine < theirs
            else "they win the trade by %s" % fmt_dur(mine - theirs) if theirs < mine else "a dead heat"))
        if randomised or v_hit < 1 or v_pen < 1:
            win = lose = draw = 0
            for _ in range(runs):
                t1 = _sim_kill(a.hp, a.dmg, a.reload, clip, intra, a.first, hit, pen, spread, rng)[0]
                t2 = _sim_kill(a.hp_self, a.vs_dmg, a.vs_reload, v_clip, v_intra, v_first, v_hit, v_pen, spread, rng)[0]
                if abs(t1 - t2) < 1e-9:
                    draw += 1
                elif t1 < t2:
                    win += 1
                else:
                    lose += 1
            more("with chance in it: you win %s, lose %s, trade %s [simulated, %d runs]" % (
                pct(win / float(runs)), pct(lose / float(runs)), pct(draw / float(runs)), runs))
    rec("SOURCE", "game values as passed in [game rule]; check the current patch or rulebook")


# ---- scenario briefs

def cmd_scenario(a):
    data = load_data("scenarios")
    if a.list:
        for key in ("missions", "terrain", "weather", "light", "opposition", "arms", "snags", "twists"):
            items = data.get(key, [])
            rec(key.upper(), "%d entries" % len(items))
            for it in items:
                more(it["name"] + ": " + it["objective"] if isinstance(it, dict) else it)
        return
    if not 1 <= a.difficulty <= 5:
        die("--difficulty is 1 to 5")
    seed = a.seed if a.seed is not None else random.SystemRandom().randint(1, 99999)
    rng = random.Random(seed)
    missions = data["missions"]
    if a.mission:
        want = a.mission.lower()
        hits = [m for m in missions if m["name"].lower().startswith(want)]
        if not hits:
            die("no mission called '%s'; missions: %s" % (a.mission, ", ".join(m["name"] for m in missions)))
        mission = hits[0]
        rng.choice(missions)
    else:
        mission = rng.choice(missions)
    terrain = rng.choice(data["terrain"])
    weather = rng.choice(data["weather"])
    light = rng.choice(data["light"])
    opposition = rng.choice(data["opposition"])
    snags = rng.sample(data["snags"], 2)
    twist = rng.choice(data["twists"])
    arms = rng.choice(data["arms"]) if a.arms else None
    rec("BRIEF", "seed %d, difficulty %d [rolled; the same seed gives the same brief]" % (seed, a.difficulty))
    rec("RULESET", a.ruleset or "lore physics (say so if %s names another)" % driver())
    rec("MISSION", mission["name"])
    rec("OBJECTIVE", mission["objective"])
    rec("TERRAIN", terrain)
    rec("WEATHER", weather)
    rec("LIGHT", light)
    rec("OPPOSITION", "none: the ground and the weather are the opponent" if a.difficulty == 1 else opposition)
    if arms:
        rec("ARMS", "%s [house rules: 'strike --list' has the figures, 'board' keeps everyone's books]" % arms)
    count = {1: 0, 2: 0, 3: 1, 4: 2, 5: 2}[a.difficulty]
    for s in snags[:count]:
        rec("SNAG", s)
    if a.difficulty == 5:
        rec("TWIST", twist + " (keep it back until it happens)")
    rec("FORCES", "FIRN-01; passengers and cores as the mission says; nobody else unless the brief adds them")
    rec("MODULES", "none fitted (list any on the brief so the scenario is honest; in his hands a module stops things, not people)")
    rec("LIVES", "every life on the board counts the same, the opposition's included; someone who is down is someone to reach")
    rec("WIN", mission["win"])
    rec("LOSS", mission["loss"])
    rec("LIMIT", mission["limit"])
    rec("NEXT", "confirm or edit the brief with %s, start the ledger with 'lattice', then run turn one. "
                "Once confirmed the brief is locked: nothing joins the board that is not on it" % driver())


def register(sub):
    p = command(sub, "combat", "lanchester", cmd_lanchester,
                "force ratios for wargames: who wins, how many are left, and the odds with whole units",
                ["lanchester 10 15 --blue-rate 0.3 --red-rate 0.1", "lanchester 12 12 --blue-rate 0.1 --red-rate 0.1 --runs 2000 --seed 7",
                 "lanchester 40 60 --blue-rate 0.02 --red-rate 0.01 --law linear --red-break 50 --trace 6"])
    p.add_argument("blue", type=float, help="blue force size")
    p.add_argument("red", type=float, help="red force size")
    p.add_argument("--blue-rate", type=float, required=True, help="red losses per blue unit per unit time")
    p.add_argument("--red-rate", type=float, required=True, help="blue losses per red unit per unit time")
    p.add_argument("--law", choices=["square", "linear"], default="square", help="square: aimed fire; linear: area fire")
    p.add_argument("--blue-break", type=float, default=0, help="blue breaks off at this percent of its start (default: fights to the end)")
    p.add_argument("--red-break", type=float, default=0, help="red breaks off at this percent of its start")
    p.add_argument("--trace", type=int, help="print this many rows of the time series")
    p.add_argument("--runs", type=int, help="also play it this many times with whole units and chance")
    p.add_argument("--seed", type=int, help="seed for --runs")
    p.add_argument("--step", type=float, default=0.01)
    p.add_argument("--max-time", type=float, default=1000)

    p = command(sub, "combat", "ttk", cmd_ttk,
                "shots and time to kill, DPM, clip guns, and a duel, from game values you pass in",
                ["ttk --hp 1800 --dmg 390 --reload 7.5", "ttk --hp 1800 --dmg 390 --reload 7.5 --hit 85 --pen 75 --rng 25 --seed 3",
                 "ttk --hp 2000 --dmg 400 --reload 24 --clip 4 --intra 2",
                 "ttk --hp 1500 --dmg 320 --reload 6 --hp-self 1650 --vs-dmg 440 --vs-reload 9.5"])
    p.add_argument("--hp", type=float, required=True, help="target hit points")
    p.add_argument("--dmg", type=float, required=True, help="average damage per shot")
    p.add_argument("--reload", type=float, required=True, help="seconds between shots (clip guns: full reload)")
    p.add_argument("--clip", type=int, help="shells per clip (autoloaders)")
    p.add_argument("--intra", type=float, help="seconds between shells inside a clip")
    p.add_argument("--first", type=float, default=0.0, help="time of the first shot (0 = already loaded)")
    p.add_argument("--hit", type=float, help="chance to hit, 0-1 or percent")
    p.add_argument("--pen", type=float, help="chance to penetrate, 0-1 or percent")
    p.add_argument("--rng", type=float, help="damage spread, plus or minus percent")
    p.add_argument("--hp-self", type=float, help="duel: your own hit points (--hp is theirs)")
    p.add_argument("--vs-dmg", type=float, help="duel: their damage per shot")
    p.add_argument("--vs-reload", type=float, help="duel: their reload")
    p.add_argument("--vs-clip", type=int)
    p.add_argument("--vs-intra", type=float)
    p.add_argument("--vs-first", type=float, default=0.0)
    p.add_argument("--vs-hit", type=float)
    p.add_argument("--vs-pen", type=float)
    p.add_argument("--runs", type=int, default=4000, help="simulation runs when chance is involved (default 4000)")
    p.add_argument("--seed", type=int)

    p = command(sub, "combat", "scenario", cmd_scenario,
                "roll a sim brief from the tables: mission, terrain, weather, light, opposition, snags",
                ["scenario", "scenario --seed 4711 --difficulty 4", "scenario --mission recon", "scenario --list",
                 "scenario --mission extraction --arms --seed 12"])
    p.add_argument("--seed", type=int, help="seed (omit for a fresh one; it is printed so the brief can be repeated)")
    p.add_argument("--difficulty", type=int, default=3, help="1 calm to 5 everything at once (default 3)")
    p.add_argument("--mission", help="fix the mission by name (delivery, extraction, escort, recon, ...)")
    p.add_argument("--ruleset", help="ruleset line for the brief")
    p.add_argument("--arms", action="store_true", help="say what the opposition carries: bows, blades, charges, beams (house rules)")
    p.add_argument("--list", action="store_true", help="list the tables")
