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
  seal  unseal              the cell on its own air, or back on outside air
  silent=on  silent=off     silent running (excludes the Veil)
  smoke=on  smoke=off       the smoke screen: a quarter of a beam gets through it
  temp=-5                   ambient temperature in C (changes how fast Rime re-cools)
  armour=1  armour=0.5      charge a docked armour from the bank: 1 is one armour from empty
  squall=5.1                a Squall burst (a jump): the km of range the jump tool said it costs; it ends silent running
  km=400  heat=90  charge=300   set by hand: a range cap, a warm start, a recharge the story grants
"""
import re

from .core import command, die, load_data, more, num, parse_duration, rec, trim, unprotect

FACES = ["front", "rear", "left", "right", "top", "under"]
# what a hit is, for the layers: a shot (the default: bullets, shells, a ram, anything built for the job), a blast,
# a beam, or a hand weapon. The maker ruled how each layer answers each kind (SKILL.md section 3).
HIT_KINDS = {"shot": "shot", "shell": "shot", "bullet": "shot", "ram": "shot",
             "blast": "blast", "explosion": "blast", "charge": "blast", "mine": "blast",
             "beam": "beam", "laser": "beam",
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
            + (["smoke=1"] if self.smoke else []))

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
            self.temp = float(kv["temp"])
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
        return c["rime_recool_cold_s"] + f * (c["rime_recool_warm_s"] - c["rime_recool_cold_s"])

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
            step = max(step, 0.0)
            self.t += step
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
        aside = ""
        if kind == "hand":
            if weight == "heavy":
                weight = "light"
            aside = " - a hand weapon: a light hit at most, whatever the arm behind it"
        weak = False
        if surprise:
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
                self.say("", "-> lost in the smoke: what arrives is not enough to matter. The smoke's capacity has no figure: the driver rules how long it lasts.")
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
            if val.lower() not in ("on", "off"):
                die("smoke=on or smoke=off")
            self.smoke = val.lower() == "on"
            self.say("SMOKE", "screen out from the sills: it breaks line of sight, thermal sights included, and lets a quarter of a beam "
                              "through. How long it lasts has no figure: the driver rules" if self.smoke else "cleared")
        elif key in ("armour", "armor"):
            self.feed_armour(val)
        elif key == "squall":
            self.squall(val)
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
                "km= heat= charge=" % event)

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
        self.say("", "how long charging takes has no figure: the driver rules")

    def squall(self, val):
        """A Squall burst: what the jump tool said it costs comes off the range. It is loud, so silent running ends."""
        try:
            km = float(val)
        except ValueError:
            die("squall=KM: the km of range the jump tool gave for the burst")
        if km <= 0:
            die("squall= takes the cost of the burst in km of range, more than 0 (the jump tool gives it)")
        if km > self.km + 1e-9:
            self.say("SQUALL", "REFUSED: the burst needs %s km of range and %s km is left" % (trim(km, 1), num(self.km, 1)))
            return
        before = self.km
        self.km = max(0.0, self.km - km)
        if self.silent:
            self.silent = False
            self.say("SILENT", "ended: a Squall is heard a long way off")
        self.say("SQUALL", "burst fired at t=%s: -%s km: range %s -> %s km [lore]" % (
            clock(self.t), trim(km, 1), num(before, 1), num(self.km, 1)))

    def summary(self):
        limit = self.cfg["veil_overheat_s"]
        rime = ", ".join("%s until t=%s" % (f, clock(u)) for f, u in sorted(self.rime.items())) or "none"
        air_left = max(0.0, self.cfg["cell_air_min"] * 60.0 - self.air)
        veil = self.veil + (" (LOCKED)" if self.lock else "")
        text = "t=%s | range %s km | Veil %s, heat %s/%d s | rime soft: %s | cell air %s left%s | %s C%s" % (
            clock(self.t), num(self.km, 1), veil, trim(self.heat, 0), limit, rime, clock(air_left),
            " (sealed)" if self.sealed else "", trim(self.temp, 1), " | silent" if self.silent else "")
        return text + (" | smoke out" if self.smoke else "")

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
                    "armour= squall=")
        rec("HITS", "hit=FACE:heavy|light, then the kind: shot (default), blast, beam or hand, and :surprise if it was not seen coming [maker]")
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
                   help="events in order: wait= drive= veil= cost= hit= seal unseal silent= smoke= temp= armour= squall= km= heat= "
                        "charge=")
    p.add_argument("--state", help="the STATE token from the previous turn (omit to start a new ledger)")
    p.add_argument("--km", type=float, help="start or override: range left, km")
    p.add_argument("--heat", type=float, help="start or override: emitter heat, s")
    p.add_argument("--temp", type=float, help="start or override: ambient temperature, C")
    p.add_argument("--kmh", type=float, default=80.0, help="speed for drive= events that give none (default 80)")
