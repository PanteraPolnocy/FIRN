"""The FIRN-01 cost ledger: Veil, Rime, Scales, Cell and range, tracked honestly between sim turns.

SKILL.md section 3 gives every layer a cost. This keeps the books so a simulation has no plot armour.
State travels as a short token, so nothing is written to disk: pass the STATE line back in with --state.

Events, applied in order:
  wait=30  wait=2m          time passes (cooling, re-cooling, air, Veil cost if it is up)
  drive=12  drive=12@90     drive 12 km (at 90 km/h; default --kmh), range and time both move
  veil=full  veil=partial:front  veil=off
  cost=full:45  cost=partial:120   preview what a Veil would cost, without raising it
  hit=front:heavy  hit=left:light  hit=rear:heavy:surprise     faces: front rear left right top under
  hit=under:heavy:blast  hit=front:light:beam  hit=left:light:hand   the kind of hit: shot (default), blast, beam, hand
  hit=front:heavy:gun       a tank's main gun: the Lattice holds two such rounds in all, until mended
  mend                      nanotech repair of one main-gun round's worth: 60 km and 20 min, and only with the Veil down
  seal  unseal              the cell on its own air, or back on outside air
  silent=on  silent=off     silent running (excludes the Veil)
  smoke=on  smoke=off       the smoke screen: three screens of 60 s; a quarter of a beam gets through it (smoke=refill in the bay)
  wade                      he has just left deep water: for ten minutes a struck Rime patch takes twice as long to re-cool
  temp=-5                   ambient temperature in C (changes how fast Rime re-cools)
  armour=1  armour=0.5      charge a docked armour from the bank: 1 is one armour from empty
  squall=5.1                a Squall burst (a jump): the km of range the jump tool said it costs; it ends silent running.
                            Two bursts back to back, then the ducts need 30 s
  spike                     the signature spike: holds a lock for 10 s, costs 10 km, ends silent running, a minute before the next
  keen=low:3  keen=high:1.8 the Keen for that many seconds (4 at most): range, its heat, and silent running on the high setting
  ram=wood@40  ram=brick@70 he drives through it: a heavy hit on the front face, or 5 km on the Veil if it is up there
                            (ram=reinforced:40@95 gives a thickness in cm; the ram tool lists what he goes through)
  km=400  heat=90  charge=300   set by hand: a range cap, a warm start, a recharge the story grants
"""
import re

from .core import command, die, load_data, more, num, parse_duration, rec, trim, unprotect
from .hull import KEEN_PEOPLE, ram_plan

FACES = ["front", "rear", "left", "right", "top", "under"]
# what a hit is, for the layers: a shot (the default: bullets, shells, a ram, anything built for the job), a blast,
# a beam, or a hand weapon. The maker ruled how each layer answers each kind (SKILL.md section 3).
HIT_KINDS = {"shot": "shot", "shell": "shot", "bullet": "shot", "ram": "shot",
             "blast": "blast", "explosion": "blast", "charge": "blast", "mine": "blast",
             "beam": "beam", "laser": "beam",
             "gun": "gun", "maingun": "gun", "tank": "gun",
             "hand": "hand", "arrow": "hand", "bolt": "hand", "spear": "hand", "blade": "hand", "club": "hand", "hammer": "hand",
             "pierce": "hand", "cut": "hand", "crush": "hand", "melee": "hand"}
OPPOSITE = {"front": "rear", "rear": "front", "left": "right", "right": "left", "top": "under", "under": "top"}
VERSION_TAG = "F2"


def _lore():
    return load_data("lore")


def clock(t):
    """Seconds as m:ss.s."""
    m, s = divmod(max(0.0, t), 60.0)
    return "%d:%04.1f" % (int(m), s)


class Ledger:
    def __init__(self, lore):
        lat = lore["lattice"]
        self.cfg = lat
        self.spike_cfg = lore["spike"]
        self.spike_ready = 0.0      # ledger time before which the signature spike cannot fire again
        self.squall_cfg, self.smoke_cfg, self.gun_cfg, self.ford_cfg = lore["squall"], lore["smoke"], lore["gun"], lore["ford"]
        self.squall_left, self.squall_last = int(self.squall_cfg["bursts"]), -1e9
        self.smoke_left, self.smoke_until = int(self.smoke_cfg["screens"]), 0.0
        self.gun = 0                # main-gun rounds the Lattice has taken and not yet mended
        self.mend_left = 0.0        # seconds of repair still to run on the round being mended
        self.spent = {}             # faces a main-gun round has spent, until their Rime re-cools
        self.wet_until = 0.0        # after wading, a struck Rime patch re-cools slower until this time
        self.keen_cfg, self.ram_cfg = lore["keen"], lore["ram"]
        self.keen_heat, self.keen_at = 0.0, 0.0     # seconds of burst the Keen had to shed, and when that was true
        self.full_km = float(lore["chassis"]["range_km"])
        self.t = 0.0
        self.km = self.full_km
        self.heat = 0.0
        self.lock = False
        self.veil = "off"
        self.rime = {}
        self.stack = None
        self.air = 0.0
        self.sealed = False
        self.silent = False
        self.smoke = False
        self.temp = 5.0
        self.lines = []

    # ---- token

    def token(self):
        rime = "+".join("%s@%s" % (f, trim(u, 1)) for f, u in sorted(self.rime.items())) or "-"
        stack = "%s@%s" % (self.stack[0], trim(self.stack[1], 2)) if self.stack else "-"
        return "/".join([
            VERSION_TAG, "t=" + trim(self.t, 2), "km=" + trim(self.km, 2), "heat=" + trim(self.heat, 2),
            "lock=%d" % self.lock, "veil=" + self.veil, "rime=" + rime, "stack=" + stack,
            "air=" + trim(self.air, 1), "seal=%d" % self.sealed, "silent=%d" % self.silent, "temp=" + trim(self.temp, 1)]
            + (["smoke=1", "su=" + trim(self.smoke_until, 2)] if self.smoke else [])
            + (["sl=%d" % self.smoke_left] if self.smoke_left < self.smoke_cfg["screens"] else [])
            + (["spike=" + trim(self.spike_ready, 2)] if self.spike_ready > self.t else [])
            + (["sq=%d@%s" % (self.squall_left, trim(self.squall_last, 2))] if self._squall_busy() else [])
            + (["gun=%d" % self.gun] if self.gun else []) + (["mend=" + trim(self.mend_left, 1)] if self.mend_left > 0 else [])
            + (["spent=" + "+".join("%s@%s" % (f, trim(u, 1)) for f, u in sorted(self.spent.items()))] if self.spent else [])
            + (["wet=" + trim(self.wet_until, 1)] if self.wet_until > self.t else [])
            + (["keen=%s@%s" % (trim(self.keen_heat, 2), trim(self.keen_at, 2))] if self.keen_warm() > 1e-9 else []))

    def keen_warm(self):
        """Seconds of burst the Keen still has to shed: a full burst cools in cool_s, a shorter one in proportion."""
        cfg = self.keen_cfg
        return max(0.0, self.keen_heat - (self.t - self.keen_at) * cfg["burst_s"] / float(cfg["cool_s"]))

    def _squall_busy(self):
        return self.squall_left < self.squall_cfg["bursts"] and self.t < self.squall_last + self.squall_cfg["again_s"]

    def load(self, token):
        parts = unprotect(token).strip().split("/")
        if not parts or parts[0] != VERSION_TAG:
            die("that is not a ledger state token (it should start with %s/); paste the STATE line exactly" % VERSION_TAG)
        try:
            kv = dict(p.split("=", 1) for p in parts[1:])
            self.t = float(kv["t"])
            self.km = float(kv["km"])
            self.heat = float(kv["heat"])
            self.lock = kv["lock"] == "1"
            self.veil = kv["veil"]
            self.rime = {}
            if kv["rime"] != "-":
                for item in kv["rime"].split("+"):
                    f, u = item.split("@")
                    self.rime[f] = float(u)
            self.stack = None
            if kv["stack"] != "-":
                f, u = kv["stack"].split("@")
                self.stack = (f, float(u))
            self.air = float(kv["air"])
            self.sealed = kv["seal"] == "1"
            self.silent = kv.get("silent", "0") == "1"
            self.smoke = kv.get("smoke", "0") == "1"
            self.spike_ready = float(kv.get("spike", "0"))
            self.temp = float(kv["temp"])
            self.smoke_until = float(kv.get("su", self.t + self.smoke_cfg["seconds"]))
            self.smoke_left = int(kv.get("sl", self.smoke_cfg["screens"]))
            if "sq" in kv:
                left, last = kv["sq"].split("@")
                self.squall_left, self.squall_last = int(left), float(last)
            self.gun = int(kv.get("gun", "0"))
            self.mend_left = float(kv.get("mend", "0"))
            self.spent = {}
            for item in kv.get("spent", "").split("+"):
                if item:
                    f, u = item.split("@")
                    self.spent[f] = float(u)
            self.wet_until = float(kv.get("wet", "0"))
            self.keen_heat, self.keen_at = 0.0, 0.0
            if "keen" in kv:
                heat, at = kv["keen"].split("@")
                self.keen_heat, self.keen_at = float(heat), float(at)
        except (KeyError, ValueError):
            die("the ledger state token is damaged; paste the STATE line exactly as printed")
        if self.veil != "off" and self.veil != "full" and self.veil.split(":")[-1] not in FACES:
            die("the ledger state token is damaged (veil)")

    # ---- rates

    def veil_rate(self, mode=None):
        """km of range per second for a Veil mode."""
        mode = self.veil if mode is None else mode
        if mode == "off":
            return 0.0
        full = self.cfg["veil_km_per_min"] / 60.0
        return full if mode == "full" else full * self.cfg["veil_partial_fraction"]

    def heat_rate(self, mode=None):
        mode = self.veil if mode is None else mode
        if mode == "off":
            return -float(self.cfg["veil_cool_ratio"])
        return 1.0 if mode == "full" else float(self.cfg["veil_partial_fraction"])

    def recool(self):
        c = self.cfg
        lo, hi = float(c["rime_cold_at_c"]), float(c["rime_warm_at_c"])
        f = 0.0 if self.temp <= lo else 1.0 if self.temp >= hi else (self.temp - lo) / (hi - lo)
        wet = float(self.ford_cfg["rime_factor"]) if self.t < self.wet_until else 1.0      # slower for a while after wading
        return (c["rime_recool_cold_s"] + f * (c["rime_recool_warm_s"] - c["rime_recool_cold_s"])) * wet

    def say(self, key, text):
        self.lines.append((key, text))

    # ---- time

    def advance(self, dt, drive_rate=0.0):
        """Let dt seconds pass. drive_rate is km of range per second spent on driving.
        Returns the seconds that did not happen because the range ran out mid-drive."""
        limit = float(self.cfg["veil_overheat_s"])
        air_limit = self.cfg["cell_air_min"] * 60.0
        left = dt
        unused = 0.0
        guard = 0
        while guard < 1000:
            guard += 1
            # things that happen in no time: an empty bank cannot feed the Veil or the motors
            if self.km <= 1e-9:
                self.km = 0.0
                if self.veil != "off":
                    self.say("EMPTY", "t=%s range exhausted: Veil dropped" % clock(self.t))
                    self.veil = "off"
                if drive_rate > 0 and left > 1e-9:
                    self.say("EMPTY", "t=%s OUT OF RANGE: stopped %s km short" % (clock(self.t), trim(drive_rate * left, 1)))
                    unused, left = left, 0.0
            if self.veil != "off" and self.heat >= limit - 1e-9:
                self.say("OVERHEAT", "t=%s emitters tripped at %d s of heat: Veil down, locked until fully cool" % (clock(self.t), limit))
                self.veil, self.lock = "off", True
            if self.lock and self.heat <= 1e-9:
                self.lock = False
                self.say("COOL", "t=%s emitters cool: Veil available again" % clock(self.t))
            if left <= 1e-9:
                break
            # the longest step before the next thing changes
            vr, hr = self.veil_rate(), self.heat_rate()
            use = vr + drive_rate
            step = left
            if use > 0:
                step = min(step, self.km / use)
            if hr > 0:
                step = min(step, (limit - self.heat) / hr)
            elif self.heat > 0:
                step = min(step, self.heat / -hr)
            if self.sealed and self.air < air_limit:
                step = min(step, air_limit - self.air)
            if self.smoke:
                step = min(step, self.smoke_until - self.t)
            mending = self.mend_left > 0 and self.veil == "off"      # the nanotech does not work under the Veil
            if mending:
                step = min(step, self.mend_left)
            step = max(step, 0.0)
            self.t += step
            if mending:
                self.mend_left -= step
                if self.mend_left <= 1e-9:
                    self.mend_left = 0.0
                    self.gun = max(0, self.gun - 1)
                    held = self.gun_cfg["rounds"] - self.gun
                    self.say("MENDED", "t=%s one main-gun round's worth of Lattice is whole again: it holds %d of %d [lore]" % (
                        clock(self.t), held, self.gun_cfg["rounds"]))
            if self.smoke and self.t >= self.smoke_until - 1e-9:
                self.smoke = False
                self.say("SMOKE", "t=%s the screen has thinned out: %d of %d left [lore]" % (
                    clock(self.t), self.smoke_left, self.smoke_cfg["screens"]))
            self.km = max(0.0, self.km - use * step)
            self.heat = min(limit, max(0.0, self.heat + hr * step))
            if self.sealed:
                was = self.air
                self.air = min(air_limit, self.air + step)
                if was < air_limit <= self.air + 1e-9:
                    self.say("AIR", "t=%s cell air exhausted after %d min: unseal, or everyone inside is in trouble" % (
                        clock(self.t), self.cfg["cell_air_min"]))
            left -= step
        for f in sorted(self.rime):
            if self.rime[f] <= self.t + 1e-9:
                self.say("RIME", "%s re-cooled at t=%s: ready again" % (f, clock(self.rime[f])))
                del self.rime[f]
                self.spent.pop(f, None)
        if self.stack and self.t - self.stack[1] > self.cfg["weak_window_s"]:
            self.stack = None
        return unused

    # ---- events

    def set_veil(self, mode):
        if mode not in ("full", "off") and not (mode.startswith("partial:") and mode.split(":", 1)[1] in FACES):
            die("veil is full, off, or partial:FACE (%s)" % ", ".join(FACES))
        if mode == self.veil:
            self.say("VEIL", "already %s" % mode)
            return
        if mode != "off":
            if self.lock:
                self.say("VEIL", "REFUSED: emitters locked after an overheat; %s s of heat still to shed" % trim(self.heat, 0))
                return
            if self.km <= 0:
                self.say("VEIL", "REFUSED: no range left to feed it")
                return
            if self.silent:
                self.silent = False
                self.say("SILENT", "ended: the Veil lights the bar frost-white")
            rate = self.veil_rate(mode) * 60.0
            room = (self.cfg["veil_overheat_s"] - self.heat) / self.heat_rate(mode)
            self.say("VEIL", "%s up at t=%s: %s km of range a minute; %s until the emitters trip; range allows %s" % (
                mode, clock(self.t), trim(rate, 1), clock(room), clock(self.km / self.veil_rate(mode))))
        else:
            self.say("VEIL", "down at t=%s; heat %s/%d s, cooling" % (clock(self.t), trim(self.heat, 0), self.cfg["veil_overheat_s"]))
        self.veil = mode

    def preview(self, spec):
        mode, _, dur = spec.partition(":")
        if mode not in ("full", "partial") or not dur:
            die("cost=full:SECONDS or cost=partial:SECONDS")
        secs = parse_duration(dur)
        vm = "full" if mode == "full" else "partial:front"
        km = self.veil_rate(vm) * secs
        heat = self.heat + self.heat_rate(vm) * secs
        limit = self.cfg["veil_overheat_s"]
        verdict = "ok" if heat < limit and km < self.km else "NOT POSSIBLE: " + (
            "emitters trip after %s" % clock((limit - self.heat) / self.heat_rate(vm)) if heat >= limit
            else "range runs out after %s" % clock(self.km / self.veil_rate(vm)))
        self.say("COST", "%s Veil for %s: -%s km (leaves %s km), heat %s -> %s/%d s -> %s [lore]" % (
            mode, clock(secs), trim(km, 1), num(max(0.0, self.km - km), 1), trim(self.heat, 0), trim(min(heat, limit), 0), limit, verdict))

    def hit(self, spec):
        parts = spec.lower().split(":")
        if len(parts) < 2 or parts[0] not in FACES or parts[1] not in ("heavy", "light"):
            die("hit=FACE:heavy or hit=FACE:light, then a kind (shot, blast, beam, hand) and :surprise if it was not seen coming "
                "(faces: %s)" % ", ".join(FACES))
        face, weight = parts[0], parts[1]
        extra = parts[2:]
        surprise = "surprise" in extra
        kinds = [HIT_KINDS[x] for x in extra if x in HIT_KINDS]
        if len(kinds) > 1 or any(x != "surprise" and x not in HIT_KINDS for x in extra):
            die("after heavy or light comes one kind of hit (shot, blast, beam, hand) and, if it was not seen coming, :surprise")
        kind = kinds[0] if kinds else "shot"
        window = self.cfg["weak_window_s"]
        covered = self.veil == "full" or self.veil == "partial:" + face
        veil_txt = "up on this face" if covered else ("up, but not on this face" if self.veil != "off" else "down")
        if kind == "beam":
            self._beam(face, weight, covered, veil_txt)
            return
        if kind == "blast":
            self._blast(face, weight, covered, veil_txt)
            return
        if kind == "gun":
            self._gun(face, covered, veil_txt, surprise)
            return
        aside = ""
        if kind == "hand":
            if weight == "heavy":
                weight = "light"
            aside = " - a hand weapon: a light hit at most, whatever the arm behind it"
        weak = False
        if face in self.spent:
            scales_ok, scales_txt = False, "SPENT by a main-gun round until t=%s" % clock(self.spent[face])
        elif surprise:
            scales_ok, scales_txt = False, "unstacked (no %d ms forecast)" % self.cfg["forecast_ms"]
        elif self.stack and self.stack[0] != face and self.t - self.stack[1] <= window + 1e-9:
            scales_ok = False
            weak = OPPOSITE[self.stack[0]] == face
            scales_txt = "THIN: tiles still stacked on the %s%s" % (
                self.stack[0], " - opposite side inside %s s, the known weakness" % trim(window, 2) if weak else "")
        else:
            scales_ok, scales_txt = True, "stacked at the impact point"
            self.stack = (face, self.t)
        rime_ok = True
        if weight == "heavy":
            if face in self.rime:
                rime_ok = False
                rime_txt = "SOFT: no bloom, load not spread (re-cools at t=%s)" % clock(self.rime[face])
            else:
                until = self.t + self.recool()
                self.rime[face] = until
                rime_txt = "bloomed and spread the load; soft until t=%s" % clock(until)
        else:
            rime_txt = "untouched (light hit)" if face not in self.rime else "still soft, not needed for a light hit"
        self.say("HIT", "t=%s %s %s%s%s" % (clock(self.t), face, weight, " (surprise)" if surprise else "", aside))
        self.say("", "veil: %s | scales: %s | rime: %s | cell: holding" % (veil_txt, scales_txt, rime_txt))
        failed = [n for n, ok in (("scales", scales_ok), ("rime", rime_ok)) if not ok]
        if not failed:
            verdict = "taken in depth" + (" behind the Veil" if covered else "")
        elif len(failed) == 2 and not covered:
            verdict = "EXPOSED: scales thin and rime soft, no Veil on this face - only the cell stands behind this hit"
        else:
            verdict = "degraded: %s not working here%s" % (" and ".join(failed), "; the Veil is the margin" if covered else "")
        if weak and not covered:
            verdict += " [known weakness]"
        self.say("", "-> " + verdict + ". The ruleset decides what that means in damage.")

    def _gun(self, face, covered, veil_txt, surprise):
        """A tank's main gun. The Lattice holds two such rounds in all, until mended. After that: the Veil stops one and
        trips at once; without it a stacked face stops one and is spent, with only the Cell behind it, until it re-cools."""
        rounds = int(self.gun_cfg["rounds"])
        limit = float(self.cfg["veil_overheat_s"])
        was_soft = face in self.rime
        if was_soft:
            rime_txt = "SOFT: no bloom, load not spread (re-cools at t=%s)" % clock(self.rime[face])
        else:
            self.rime[face] = self.t + self.recool()
            rime_txt = "bloomed and spread the load; soft until t=%s" % clock(self.rime[face])
        self.say("HIT", "t=%s %s main-gun round%s" % (clock(self.t), face, " (surprise)" if surprise else ""))
        if self.gun < rounds:
            self.gun += 1
            self.say("", "veil: %s | lattice: holds, round %d of the %d it takes before mending | rime: %s | cell: holding" % (
                veil_txt, self.gun, rounds, rime_txt))
            self.say("", "-> held [lore]. The ruleset decides what that means in damage. 'mend' gives a round back: %d min and %d km, "
                         "Veil down" % (self.gun_cfg["mend_min"], self.gun_cfg["mend_km"]))
            return
        if covered:
            self.heat, self.veil, self.lock = limit, "off", True
            self.say("", "veil: stops it, and the emitters trip at once: Veil down, locked until fully cool | lattice: its %d rounds "
                         "are spent | rime: %s | cell: holding" % (rounds, rime_txt))
            self.say("", "-> stopped on the Veil, which is gone until the emitters cool [lore]. The ruleset decides what that means in damage.")
            return
        stacked = not surprise and face not in self.spent and not was_soft
        if stacked:
            self.spent[face] = self.rime[face]
            self.stack = (face, self.t)
            self.say("", "veil: %s | lattice: its %d rounds are spent; the stacked face stops this one and is itself spent | rime: %s | "
                         "cell: holding" % (veil_txt, rounds, rime_txt))
            self.say("", "-> stopped, at the price of the %s face: only the cell stands behind it until t=%s [lore]. The ruleset "
                         "decides what that means in damage." % (face, clock(self.spent[face])))
        else:
            self.say("", "veil: %s | lattice: its %d rounds are spent, and this face cannot stack%s | rime: %s | cell: holding" % (
                veil_txt, rounds, " (no warning)" if surprise else "", rime_txt))
            self.say("", "-> EXPOSED: only the cell stands behind this round. The ruleset decides what that means in damage.")

    def mend(self, val):
        """Nanotech repair: one main-gun round's worth of Lattice for range and time. It does not work under the Veil."""
        if val:
            die("mend takes no value: it mends one round's worth at a time")
        cfg = self.gun_cfg
        if self.gun <= 0:
            self.say("MEND", "nothing to mend: the Lattice holds its %d rounds" % cfg["rounds"])
        elif self.mend_left > 0:
            self.say("MEND", "already mending: %s to go%s" % (clock(self.mend_left), "" if self.veil == "off" else ", paused while the Veil is up"))
        elif self.veil != "off":
            self.say("MEND", "REFUSED: the nanotech cannot work with the Veil up")
        elif cfg["mend_km"] > self.km + 1e-9:
            self.say("MEND", "REFUSED: mending a round needs %s km of range and %s km is left" % (trim(cfg["mend_km"], 0), num(self.km, 1)))
        else:
            before = self.km
            self.km -= cfg["mend_km"]
            self.mend_left = cfg["mend_min"] * 60.0
            self.say("MEND", "started at t=%s: -%s km: range %s -> %s km; one round's worth is whole again at t=%s if the Veil stays "
                             "down. He may drive meanwhile [lore]" % (clock(self.t), trim(cfg["mend_km"], 0), num(before, 1), num(self.km, 1),
                                                                      clock(self.t + self.mend_left)))

    def wade(self, val):
        if val:
            die("wade takes no value: it marks the moment he leaves deep water")
        cfg = self.ford_cfg
        self.wet_until = self.t + cfg["rime_window_s"]
        self.say("WADE", "out of deep water at t=%s: until t=%s a struck Rime patch takes %s as long to re-cool, %s s at this "
                         "temperature [lore]" % (clock(self.t), clock(self.wet_until),
                                                 "twice" if cfg["rime_factor"] == 2 else "%s times" % trim(cfg["rime_factor"], 1),
                                                 trim(self.recool(), 0)))

    def _blast(self, face, weight, covered, veil_txt):
        """A blast is an area load: nothing for the Scales to stack against; the Rime and the Cell do the work."""
        rime_ok = True
        if weight == "heavy":
            if face in self.rime:
                rime_ok = False
                rime_txt = "SOFT: no bloom, load not spread (re-cools at t=%s)" % clock(self.rime[face])
            else:
                until = self.t + self.recool()
                self.rime[face] = until
                rime_txt = "bloomed and spread the load; soft until t=%s" % clock(until)
        else:
            rime_txt = "untouched (light blast)" if face not in self.rime else "still soft, not needed for a light blast"
        self.say("HIT", "t=%s %s %s blast" % (clock(self.t), face, weight))
        self.say("", "veil: %s | scales: unstacked, a blast gives them no point to stack against | rime: %s | cell: holding, "
                     "pressure, fragments and gas kept out" % (veil_txt, rime_txt))
        if covered:
            verdict = "taken on the Veil" + ("" if rime_ok else "; the Rime behind it is soft")
        elif rime_ok:
            verdict = "spread by the Rime" if weight == "heavy" else "shrugged off"
        else:
            verdict = "EXPOSED: rime soft, nothing to stack against, no Veil on this face - only the cell stands behind this blast"
        self.say("", "-> " + verdict + ". The ruleset decides what that means in damage.")

    def _beam(self, face, weight, covered, veil_txt):
        """A beam arrives with no warning and works by staying on one spot: the Veil scatters it, or the Rime drinks it once."""
        self.say("HIT", "t=%s %s %s beam%s" % (clock(self.t), face, weight, " through the smoke" if self.smoke and not covered else ""))
        if covered:
            self.say("", "veil: up on this face, and it scatters the beam | scales: not needed | rime: untouched | cell: holding")
            self.say("", "-> scattered by the Veil, at the Veil's usual cost. The ruleset decides what that means in damage.")
            return
        scales_txt = "cannot stack in time against light"
        if self.smoke:
            veil_txt += " | smoke: a quarter gets through"
            if weight == "light":
                self.say("", "veil: %s | scales: %s | rime: untouched | cell: holding" % (veil_txt, scales_txt))
                self.say("", "-> lost in the smoke: what arrives is not enough to matter. The ruleset decides what that means in damage.")
                return
            weight = "light"
        if face in self.rime:
            self.say("", "veil: %s | scales: %s | rime: SOFT, nothing left to drink the heat (re-cools at t=%s) | cell: holding" % (
                veil_txt, scales_txt, clock(self.rime[face])))
            self.say("", "-> EXPOSED: a beam on a face that is already soft - only the cell stands behind it. "
                         "The ruleset decides what that means in damage.")
            return
        until = self.t + self.recool()
        self.rime[face] = until
        self.say("", "veil: %s | scales: %s | rime: drank the heat and boiled off; soft until t=%s | cell: holding" % (
            veil_txt, scales_txt, clock(until)))
        self.say("", "-> stopped by the Rime, once: a second beam on that face before it re-cools finds only the cell. Turn the face "
                     "away, raise the Veil, or put smoke between. The ruleset decides what that means in damage.")

    def apply(self, event, default_kmh):
        ev = unprotect(event).strip()
        key, _, val = ev.partition("=")
        key = key.lower()
        if key == "wait":
            secs = parse_duration(val)
            if secs < 0:
                die("wait cannot be negative")
            self.advance(secs)
        elif key == "drive":
            dist, _, sp = val.partition("@")
            try:
                km = float(dist)
                kmh = float(sp) if sp else default_kmh
            except ValueError:
                die("drive=KM or drive=KM@KMH")
            if km < 0 or kmh <= 0:
                die("drive needs a positive distance and speed")
            if self.silent and kmh > 60:
                self.say("NOTE", "silent running at %s km/h is the narrator's call; the brief may cap it" % trim(kmh, 0))
            before = self.km
            unused = self.advance(km / kmh * 3600.0, kmh / 3600.0)
            done = km - unused * kmh / 3600.0
            self.say("DRIVE", "%s%s km at %s km/h (%s): range %s -> %s km" % (
                trim(done, 1), "" if unused <= 0 else " of %s" % trim(km, 1), trim(kmh, 0),
                clock(done / kmh * 3600.0), num(before, 1), num(self.km, 1)))
        elif key == "veil":
            self.set_veil(val.lower())
        elif key == "cost":
            self.preview(val.lower())
        elif key == "hit":
            self.hit(val)
        elif key == "seal":
            self.sealed = True
            left = max(0.0, self.cfg["cell_air_min"] * 60.0 - self.air)
            self.say("CELL", "sealed on its own air at t=%s: %s left" % (clock(self.t), clock(left)))
        elif key == "unseal":
            self.sealed = False
            spent = self.air >= self.cfg["cell_air_min"] * 60.0 - 1e-9
            self.say("CELL", "back on outside air at t=%s; %s of independent air used%s" % (
                clock(self.t), clock(self.air), ": the supply is exhausted" if spent else " so far"))
        elif key == "silent":
            if val.lower() not in ("on", "off"):
                die("silent=on or silent=off")
            self.silent = val.lower() == "on"
            if self.silent and self.veil != "off":
                self.veil = "off"
                self.say("VEIL", "down: silent running needs the bar dark")
            self.say("SILENT", "running silent: bar dark, motors hushed" if self.silent else "off")
        elif key == "smoke":
            want = val.lower()
            cfg = self.smoke_cfg
            if want not in ("on", "off", "refill"):
                die("smoke=on, smoke=off or smoke=refill")
            if want == "refill":
                self.smoke_left = int(cfg["screens"])
                self.say("SMOKE", "refilled: %d screens of %d s [by hand: back in the bay]" % (cfg["screens"], cfg["seconds"]))
            elif want == "off":
                self.say("SMOKE", "cleared: that screen is spent, %d of %d left" % (self.smoke_left, cfg["screens"]) if self.smoke
                         else "none out")
                self.smoke = False
            elif self.smoke:
                self.say("SMOKE", "already out until t=%s" % clock(self.smoke_until))
            elif self.smoke_left <= 0:
                self.say("SMOKE", "REFUSED: all %d screens are spent, and they are refilled in the bay [lore]" % cfg["screens"])
            else:
                self.smoke_left -= 1
                self.smoke, self.smoke_until = True, self.t + cfg["seconds"]
                self.say("SMOKE", "screen out from the sills until t=%s: it breaks line of sight, thermal sights included, and lets a "
                                  "quarter of a beam through; %d of %d screens left [lore]" % (clock(self.smoke_until), self.smoke_left, cfg["screens"]))
        elif key in ("armour", "armor"):
            self.feed_armour(val)
        elif key == "squall":
            self.squall(val)
        elif key == "spike":
            self.spike(val)
        elif key == "keen":
            self.keen(val)
        elif key == "ram":
            self.ram(val)
        elif key == "mend":
            self.mend(val)
        elif key == "wade":
            self.wade(val)
        elif key in ("temp", "km", "heat", "charge"):
            try:
                x = float(val)
            except ValueError:
                die("%s needs a number" % key)
            if key == "temp":
                self.temp = x
                self.say("TEMP", "%s C: a struck Rime patch now takes %s s to re-cool" % (trim(x, 1), trim(self.recool(), 0)))
            elif key == "km":
                self.km = max(0.0, min(self.full_km, x))
                self.say("SET", "range set to %s km [by hand]" % num(self.km, 1))
            elif key == "heat":
                self.heat = max(0.0, min(float(self.cfg["veil_overheat_s"]), x))
                self.say("SET", "emitter heat set to %s s [by hand]" % trim(self.heat, 0))
            else:
                self.km = max(0.0, min(self.full_km, self.km + x))
                self.say("CHARGE", "+%s km granted by the story: range %s km [by hand]" % (trim(x, 1), num(self.km, 1)))
        else:
            die("unknown ledger event '%s'. Events: wait= drive= veil= cost= hit= seal unseal silent= smoke= temp= armour= squall= "
                "spike keen= ram= mend wade km= heat= charge=" % event)

    def feed_armour(self, val):
        """Charge a docked armour from the bank. val is how many full charges: 1 is one armour from empty."""
        per = self.cfg.get("cradle_charge_km")
        slots = self.cfg.get("cradle_cores", 2)
        try:
            n = float(val)
        except ValueError:
            die("armour=1 charges one docked armour from empty; armour=0.5 is half a charge")
        if n <= 0 or n > slots:
            die("armour= takes more than 0 and at most %s (the cradle holds %s)" % (trim(slots, 0), trim(slots, 0)))
        if not per:
            self.say("ARMOUR", "no figure on file for what charging a docked armour costs: the driver rules, then set the range with km=")
            return
        want = n * float(per)
        given = min(want, self.km)
        before = self.km
        self.km = max(0.0, self.km - given)
        what = "one docked armour charged from empty" if abs(n - 1) < 1e-9 else "%s full charges into docked armour" % trim(n, 2)
        self.say("ARMOUR", "%s: -%s km: range %s -> %s km [lore]" % (what, trim(given, 1), num(before, 1), num(self.km, 1)))
        if given < want - 1e-9:
            self.say("", "the bank ran dry: only %s%% of that charge was delivered" % trim(given / want * 100.0, 0))
        mins = self.cfg.get("cradle_charge_min")
        self.say("", "that takes %s [lore: %d min from empty]: add wait= for it" % (clock(n * mins * 60.0), mins) if mins
                 else "how long charging takes has no figure: the driver rules")

    def squall(self, val):
        """A Squall burst: what the jump tool said it costs comes off the range. It is loud, so silent running ends."""
        try:
            km = float(val)
        except ValueError:
            die("squall=KM: the km of range the jump tool gave for the burst")
        if km <= 0:
            die("squall= takes the cost of the burst in km of range, more than 0 (the jump tool gives it)")
        cfg = self.squall_cfg
        if self.t >= self.squall_last + cfg["again_s"] - 1e-9:
            self.squall_left = int(cfg["bursts"])
        if self.squall_left <= 0:
            self.say("SQUALL", "REFUSED: both bursts are spent, and the ducts are not ready before t=%s [lore]" % clock(
                self.squall_last + cfg["again_s"]))
            return
        if km > self.km + 1e-9:
            self.say("SQUALL", "REFUSED: the burst needs %s km of range and %s km is left" % (trim(km, 1), num(self.km, 1)))
            return
        before = self.km
        self.km = max(0.0, self.km - km)
        self.squall_left -= 1
        self.squall_last = self.t
        if self.silent:
            self.silent = False
            self.say("SILENT", "ended: a Squall is heard a long way off")
        self.say("SQUALL", "burst fired at t=%s: -%s km: range %s -> %s km [lore]" % (
            clock(self.t), trim(km, 1), num(before, 1), num(self.km, 1)))
        self.say("", "%s; the ducts are ready again %d s after the last burst [lore]" % (
            "one more burst may follow at once" if self.squall_left else "both bursts are spent", cfg["again_s"]))

    def spike(self, val):
        """The signature spike: a burst of emissions that pulls a targeting system onto him. It holds the lock for a few
        seconds, costs range, cannot be silent, and needs a minute before the next."""
        if val:
            die("spike takes no value: it fires once")
        cfg = self.spike_cfg
        if self.t < self.spike_ready - 1e-9:
            self.say("SPIKE", "REFUSED: the last one fired at t=%s and the next is not ready before t=%s" % (
                clock(self.spike_ready - cfg["again_s"]), clock(self.spike_ready)))
            return
        if cfg["km"] > self.km + 1e-9:
            self.say("SPIKE", "REFUSED: a spike needs %s km of range and %s km is left" % (trim(cfg["km"], 1), num(self.km, 1)))
            return
        before = self.km
        self.km = max(0.0, self.km - cfg["km"])
        self.spike_ready = self.t + cfg["again_s"]
        if self.silent:
            self.silent = False
            self.say("SILENT", "ended: a spike is a shout on every band")
        self.say("SPIKE", "fired at t=%s: it holds their lock until t=%s; -%s km: range %s -> %s km; ready again at t=%s [lore]" % (
            clock(self.t), clock(self.t + cfg["lock_s"]), trim(cfg["km"], 1), num(before, 1), num(self.km, 1), clock(self.spike_ready)))

    def keen(self, val):
        """The Keen, his one fitted weapon: a burst on the low or the high setting. It costs range by the second, may not run
        past its thermal limit, and the high setting ends silent running. The burst takes its own time on the clock."""
        setting, _, dur = val.lower().partition(":")
        cfg = self.keen_cfg
        burst = float(cfg["burst_s"])
        if setting not in ("low", "high"):
            die("keen=low:SECONDS or keen=high:SECONDS, %s s at most" % trim(burst, 0))
        try:
            secs = float(dur) if dur else burst
        except ValueError:
            die("keen=low:SECONDS or keen=high:SECONDS, %s s at most" % trim(burst, 0))
        if secs <= 0:
            die("a burst lasts more than 0 s")
        warm = self.keen_warm()
        room = burst - warm
        full_at = self.t + warm * cfg["cool_s"] / burst
        if room <= 1e-9:
            self.say("KEEN", "REFUSED: at its thermal limit; it has cooled for a full burst at t=%s [lore]" % clock(full_at))
            return
        fire = min(secs, room)
        rate = cfg["high_km_s"] * (1.0 if setting == "high" else cfg["low_fraction"])
        if rate * fire > self.km + 1e-9:
            self.say("KEEN", "REFUSED: that burst needs %s km of range and %s km is left" % (trim(rate * fire, 1), num(self.km, 1)))
            return
        if setting == "high" and self.silent:
            self.silent = False
            self.say("SILENT", "ended: the Keen's high setting is heard")
        start, before = self.t, self.km
        self.km = max(0.0, self.km - rate * fire)
        self.advance(fire)
        self.keen_heat, self.keen_at = warm + fire, self.t
        self.say("KEEN", "%s setting for %s s from t=%s: -%s km: range %s -> %s km; cool for a full burst at t=%s [lore]" % (
            setting, trim(fire, 1), clock(start), trim(rate * fire, 1), num(before, 1), num(self.km, 1),
            clock(self.t + self.keen_heat * cfg["cool_s"] / burst)))
        if fire < secs - 1e-9:
            self.say("", "cut off at its %s s thermal limit: %s s of the %s asked for" % (trim(burst, 0), trim(fire, 1), trim(secs, 1)))
        if setting == "low":
            self.say("", "a camera or a lidar in the beam inside %d m is blind until t=%s; it does nothing to people [lore]" % (
                cfg["low_reach_m"], clock(self.t + cfg["linger_s"])))
        else:
            self.say("", "inside %d m: laminated glass, drone rotors, light barricades (the keen tool says which, and how long it "
                         "takes); %s" % (cfg["high_reach_m"], KEEN_PEOPLE))

    def ram(self, val):
        """He drives the hull through something. With the Veil on the front face it takes the blow for a set cost in range;
        with it down the light things are one heavy hit on the front face, and the rest has no figure or stops him."""
        spec, _, sp = val.lower().partition("@")
        thing, _, thick = spec.partition(":")
        try:
            kmh = float(sp) if sp else None
            cm = float(thick) if thick else None
        except ValueError:
            die("ram=THING, ram=THING@KMH or ram=reinforced:CM@KMH")
        if not thing:
            die("ram=THING: say what is in the way (the ram tool lists them)")
        covered = self.veil in ("full", "partial:front")
        plan = ram_plan(self.ram_cfg, thing, covered, kmh, cm)
        head = "t=%s %s%s, %s" % (clock(self.t), plan["name"], "" if kmh is None else " at %s km/h" % trim(kmh, 0),
                                  "armour up" if covered else "Veil down")
        if plan["result"] == "free":
            self.say("RAM", "%s: through, and it costs nothing [lore]" % head)
        elif plan["result"] == "nofigure":
            self.say("RAM", "%s: NO FIGURE: %s" % (head, plan["why"]))
        elif plan["result"] in ("stop", "slow"):
            self.say("RAM", "%s: NOT THROUGH: %s" % (head, plan["why"]))
            if plan["result"] == "stop":
                self.say("", "what stopping against it does to him and to those aboard has no figure: the driver rules")
        elif plan["km"]:
            if plan["km"] > self.km + 1e-9:
                self.say("RAM", "%s: REFUSED: the breach needs %s km of range for the Veil and %s km is left" % (
                    head, trim(plan["km"], 1), num(self.km, 1)))
                return
            before = self.km
            self.km -= plan["km"]
            self.say("RAM", "%s: through on the Veil, which holds: -%s km: range %s -> %s km; the front face stays fresh [lore]" % (
                head, trim(plan["km"], 1), num(before, 1), num(self.km, 1)))
            if plan["frame"]:
                self.say("", "it damages his frame [maker]: how much has no figure, the driver rules")
        else:
            self.say("RAM", "%s: through, as one heavy hit on the front face [lore]" % head)
            self.hit("front:heavy:ram")
        if kmh is None and plan["result"] == "through":
            self.say("", "it needs %d km/h at least [maker]" % plan["need"])

    def summary(self):
        limit = self.cfg["veil_overheat_s"]
        rime = ", ".join("%s until t=%s" % (f, clock(u)) for f, u in sorted(self.rime.items())) or "none"
        air_left = max(0.0, self.cfg["cell_air_min"] * 60.0 - self.air)
        veil = self.veil + (" (LOCKED)" if self.lock else "")
        text = "t=%s | range %s km | Veil %s, heat %s/%d s | rime soft: %s | cell air %s left%s | %s C%s" % (
            clock(self.t), num(self.km, 1), veil, trim(self.heat, 0), limit, rime, clock(air_left),
            " (sealed)" if self.sealed else "", trim(self.temp, 1), " | silent" if self.silent else "")
        text += " | smoke out until t=%s" % clock(self.smoke_until) if self.smoke else ""
        if self.gun:
            text += " | main-gun rounds taken %d/%d" % (self.gun, self.gun_cfg["rounds"])
        if self.mend_left > 0:
            text += " | mending, %s to go" % clock(self.mend_left)
        if self.keen_warm() > 1e-9:
            text += " | Keen cooling, %s s of burst ready" % trim(self.keen_cfg["burst_s"] - self.keen_warm(), 1)
        return text

    def warnings(self):
        out = []
        limit = self.cfg["veil_overheat_s"]
        if self.veil != "off":
            room = (limit - self.heat) / self.heat_rate()
            if room <= 30:
                out.append("%s of Veil left before the emitters trip" % clock(room))
            if self.km / self.veil_rate() <= 60:
                out.append("range feeds the Veil for only %s more" % clock(self.km / self.veil_rate()))
        if self.km < 0.1 * self.full_km:
            out.append("range under 10 percent")
        air_left = self.cfg["cell_air_min"] * 60.0 - self.air
        if self.sealed and air_left <= 600:
            out.append("cell air: %s left" % clock(max(0.0, air_left)))
        return out


def cmd_lattice(a):
    lore = _lore()
    led = Ledger(lore)
    fresh = not a.state
    if a.state:
        led.load(a.state)
    if a.km is not None:
        led.km = max(0.0, min(led.full_km, a.km))
    if a.heat is not None:
        led.heat = max(0.0, min(float(led.cfg["veil_overheat_s"]), a.heat))
    if a.temp is not None:
        led.temp = a.temp
    for ev in a.events:
        led.apply(ev, a.kmh)
    if fresh and not a.events:
        rec("LEDGER", "new [lore]: %s" % led.summary())
    for key, text in led.lines:
        rec(key, text)
    if not (fresh and not a.events):
        rec("LEDGER", led.summary())
    for w in led.warnings():
        rec("WARNING", w)
    rec("STATE", led.token())
    if fresh and not a.events:
        rec("NEXT", "pass that STATE back with --state and add events: wait= drive= veil= cost= hit= seal unseal silent= smoke= temp= "
                    "armour= squall= spike keen= ram= mend wade")
        rec("HITS", "hit=FACE:heavy|light, then the kind: shot (default), blast, beam, hand or gun (a tank's main gun), and :surprise if "
                    "it was not seen coming [maker]")
        per = led.cfg.get("cradle_charge_km")
        rec("RULES", "Veil %s km/min full, %s of that for one face; emitters trip at %d s of heat; Rime re-cools in %d-%d s; "
                     "cell air %d min; a docked armour charged from empty costs %s [lore]" % (
                         trim(led.cfg["veil_km_per_min"], 1), trim(led.cfg["veil_partial_fraction"], 2), led.cfg["veil_overheat_s"],
                         led.cfg["rime_recool_cold_s"], led.cfg["rime_recool_warm_s"], led.cfg["cell_air_min"],
                         ("%s km" % trim(per, 1)) if per else "no figure"))


def register(sub):
    p = command(sub, "firn", "lattice", cmd_lattice,
                "FIRN-01's cost ledger for sims: Veil range and heat, Rime patches, the Scales weakness, cell air",
                ["lattice --temp -3", "lattice --state F2/... veil=full wait=45 hit=left:heavy wait=0.3 hit=right:heavy veil=off",
                 "lattice --state F2/... cost=full:120", "lattice --state F2/... drive=12@90 seal wait=5m",
                 "lattice --state F2/... armour=1", "lattice hit=under:heavy:blast wait=20 hit=front:light:beam smoke=on hit=left:heavy:beam"])
    p.add_argument("events", nargs="*",
                   help="events in order: wait= drive= veil= cost= hit= seal unseal silent= smoke= temp= armour= squall= spike "
                        "keen= ram= mend wade km= heat= charge=")
    p.add_argument("--state", help="the STATE token from the previous turn (omit to start a new ledger)")
    p.add_argument("--km", type=float, help="start or override: range left, km")
    p.add_argument("--heat", type=float, help="start or override: emitter heat, s")
    p.add_argument("--temp", type=float, help="start or override: ambient temperature, C")
    p.add_argument("--kmh", type=float, default=80.0, help="speed for drive= events that give none (default 80)")
