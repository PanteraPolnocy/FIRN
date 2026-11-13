"""Energy: FIRN-01's lore range budget, real EV range and charging, fuel and trip cost."""
import math

from .core import command, die, fmt_hm, load_data, more, num, rec, table, trim

# Rule-of-thumb extra consumption against a mild day, by ambient temperature (C). Heat-pump car; resistive heaters do worse.
TEMP_PENALTY = [(-20, 0.35), (-10, 0.25), (-5, 0.20), (0, 0.15), (5, 0.10), (15, 0.03), (25, 0.0), (35, 0.05)]
CO2_KG_PER_L = {"petrol": 2.3, "diesel": 2.7, "lpg": 1.6}
L_PER_GAL_US = 3.785411784
L_PER_GAL_UK = 4.54609
KM_PER_MI = 1.609344
# For a car nobody has a figure for (fuel --kg): a model, built on three published numbers.
# Lower heating values in Btu per US gallon [US DOE, Alternative Fuels Data Center, Fuel Properties Comparison];
# petrol is the middle of its range for gasoline and E10.
LHV_BTU_GAL = {"petrol": (112114 + 116090) / 2.0, "diesel": 128488.0, "lpg": 84250.0}
J_PER_BTU = 1055.056
# the share of the energy put in that reaches the wheels in highway driving [fueleconomy.gov, Where the Energy Goes:
# Gasoline Vehicles, and Electric Cars with the energy won back in braking counted]
WHEEL_SHARE = {"petrol": (0.22, 0.30), "electric": (0.77, 0.79)}
# how much farther a diesel goes on a gallon than its petrol counterpart [fueleconomy.gov, Diesel Vehicles]
DIESEL_FARTHER = (1.20, 1.35)
FUELS = sorted(CO2_KG_PER_L) + ["electric"]


def kwh_per_litre(fuel):
    return LHV_BTU_GAL[fuel] * J_PER_BTU / L_PER_GAL_US / 3.6e6


def estimate_use(fuel, kg, kmh, cda, crr):
    """(low, middle, high) consumption on a level road at a steady speed: l/100 km, or kWh/100 km for electric.
    The wheels' share of the energy is the published highway range, so the spread is the source's, not ours."""
    from .dynamics import road_load_kw
    wheels = road_load_kw(kmh / 3.6, kg, cda, crr) / kmh * 100.0       # kWh per 100 km at the wheels
    if fuel == "electric":
        lo, hi = WHEEL_SHARE["electric"]
        return wheels / hi, wheels / ((lo + hi) / 2.0), wheels / lo
    lo, hi = WHEEL_SHARE["petrol"]
    petrol = [wheels / share / kwh_per_litre("petrol") for share in (hi, (lo + hi) / 2.0, lo)]
    if fuel == "lpg":           # the same engine on a fuel with less energy in each litre
        return tuple(x * kwh_per_litre("petrol") / kwh_per_litre("lpg") for x in petrol)
    if fuel == "diesel":
        f_lo, f_hi = DIESEL_FARTHER
        return petrol[0] / f_hi, petrol[1] / ((f_lo + f_hi) / 2.0), petrol[2] / f_lo
    return tuple(petrol)


def temp_penalty(c):
    pts = TEMP_PENALTY
    if c <= pts[0][0]:
        return pts[0][1]
    if c >= pts[-1][0]:
        return pts[-1][1]
    for (t1, p1), (t2, p2) in zip(pts, pts[1:]):
        if t1 <= c <= t2:
            return p1 + (p2 - p1) * (c - t1) / float(t2 - t1)
    return 0.0


# ---- range (lore, with the 1.2.0 real-EV shortcut kept)

def cmd_range(a):
    if a.battery_kwh:
        if not a.kwh_per_100:
            die("--kwh-per-100 is required with --battery-kwh")
        usable = a.battery_kwh * a.soc / 100.0 * (1 - a.penalty / 100.0)
        km = usable / a.kwh_per_100 * 100.0
        reserve_km = km * a.reserve / 100.0
        rec("MODE", "real EV [estimate] (for charging and trip planning use 'ev')")
        rec("ENERGY", "%s kWh usable (charge %s%%, cold or other penalty %s%%)" % (trim(usable, 1), trim(a.soc, 0), trim(a.penalty, 0)))
        rec("RANGE", "~%s km, keep %s km in reserve -> plan %s km" % (num(km), num(reserve_km), num(km - reserve_km)))
        if a.distance:
            spare = km - reserve_km - a.distance
            rec("TRIP", "%s km -> %s" % (num(a.distance), ("margin %s km" % num(spare)) if spare >= 0
                                         else ("SHORT by %s km, a charge stop is needed" % num(-spare))))
        return
    lore = load_data("lore")
    lat = lore["lattice"]
    full = float(lore["chassis"]["range_km"])
    start = a.km_left if a.km_left is not None else full
    rate = a.veil_rate if a.veil_rate is not None else lat["veil_km_per_min"]
    part = lat["veil_partial_fraction"]
    veil = a.veil_full * rate + a.veil_partial * rate * part
    left = start - veil
    rec("MODE", "FIRN-01 lore physics [lore]")
    rec("START", "%s km of %s km" % (num(start), num(full)))
    if veil:
        rec("VEIL", "full %s min + partial %s min = -%s km (%s km/min full, %s for one face)" % (
            trim(a.veil_full, 1), trim(a.veil_partial, 1), num(veil), trim(rate, 1), trim(rate * part, 1)))
    limit_min = lat["veil_overheat_s"] / 60.0
    if a.veil_full > limit_min or a.veil_partial > limit_min / part:
        rec("HEAT", "check continuity: emitters trip after %s min of continuous full Veil (%s min for one face)" % (
            trim(limit_min, 1), trim(limit_min / part, 0)))
    if a.distance:
        left -= a.distance
        rec("TRIP", "-%s km" % num(a.distance))
    rec("LEFT", "%s km%s" % (num(left), "" if left >= 0 else "  OUT OF RANGE"))
    rec("NOTE", "for a turn-by-turn budget with heat, Rime and cell air, use 'lattice'")


# ---- ev

def charge_profile(a):
    """(power kW at a state of charge 0-100) for the charger and car given."""
    peak = min(a.kw, a.car_max) if a.car_max else a.kw
    if a.ac:
        return lambda soc: peak
    knee, tail = a.knee, a.tail

    def power(soc):
        if soc <= knee:
            return peak
        return peak * (1.0 - (1.0 - tail) * (soc - knee) / (100.0 - knee))
    return power


def charge_time_h(battery, soc_from, soc_to, power):
    """Hours to take the pack from one state of charge to another."""
    if soc_to <= soc_from:
        return 0.0
    steps = 400
    h = 0.0
    width = (soc_to - soc_from) / float(steps)
    for i in range(steps):
        soc = soc_from + (i + 0.5) * width
        h += battery * width / 100.0 / max(0.1, power(soc))
    return h


def _consumption(a):
    """kWh per 100 km after temperature and speed adjustments, and the notes that explain it."""
    base = a.kwh_100
    notes = []
    cons = base
    if a.temp is not None:
        pen = temp_penalty(a.temp)
        cons *= 1.0 + pen
        notes.append("%s C adds %s%% [rule of thumb]" % (trim(a.temp, 0), trim(pen * 100, 0)))
    if a.speed and a.ref_speed:
        factor = 0.4 + 0.6 * (a.speed / a.ref_speed) ** 2
        cons *= factor
        notes.append("%s km/h against %s km/h: x%s [estimate: drag grows with speed squared]" % (
            trim(a.speed, 0), trim(a.ref_speed, 0), trim(factor, 2)))
    return cons, notes


def cmd_ev(a):
    if a.battery <= 0:
        die("--battery must be positive (usable kWh)")
    if a.what in ("range", "trip") and not a.kwh_100:
        die("--kwh-100 is needed: the car's consumption in kWh per 100 km")
    if a.what == "range":
        cons, notes = _consumption(a)
        usable = a.battery * (a.soc - a.floor) / 100.0
        if usable <= 0:
            die("--soc must be above --floor")
        km = usable / cons * 100.0
        rec("PACK", "%s kWh usable, from %s%% down to %s%% = %s kWh" % (trim(a.battery, 1), trim(a.soc, 0), trim(a.floor, 0), trim(usable, 1)))
        rec("USE", "%s kWh/100 km (%s Wh/km)%s" % (trim(cons, 1), num(cons * 10), "" if not notes else " after adjustments"))
        for n in notes:
            more(n)
        rec("RANGE", "~%s km [estimate]" % num(km))
        if a.distance:
            spare = km - a.distance
            rec("TRIP", "%s km -> %s" % (num(a.distance), "arrives with %s km in hand above the floor" % num(spare) if spare >= 0
                                         else "SHORT by %s km: plan a stop with 'ev trip'" % num(-spare)))
        return
    if a.kw <= 0:
        die("--kw must be positive (charger power)")
    power = charge_profile(a)
    loss = a.loss if a.loss is not None else (12.0 if a.ac else 8.0)
    if a.what == "charge":
        if not 0 <= a.start < a.to <= 100:
            die("charge goes from --start to --to, both 0-100, upwards")
        h = charge_time_h(a.battery, a.start, a.to, power)
        added = a.battery * (a.to - a.start) / 100.0
        grid = added / (1.0 - loss / 100.0)
        rec("CHARGE", "%s%% -> %s%% of %s kWh: +%s kWh in %s [estimate]" % (
            trim(a.start, 0), trim(a.to, 0), trim(a.battery, 1), trim(added, 1), fmt_hm(h)))
        shape = "steady %s kW (AC)" % trim(power(50), 1) if a.ac else "%s kW to %s%%, tapering to %s kW at 100%%" % (
            trim(power(0), 0), trim(a.knee, 0), trim(power(100), 0))
        rec("CURVE", "%s; average %s kW [model: real curves vary by car and temperature]" % (shape, trim(added / h, 0)))
        rec("GRID", "%s kWh drawn at %s%% charging loss" % (trim(grid, 1), trim(loss, 0)))
        if a.price:
            rec("COST", "%s at %s per kWh" % (num(grid * a.price, 2), trim(a.price, 2)))
        if a.kwh_100:
            cons, _ = _consumption(a)
            rec("ADDS", "~%s km of range, %s km per minute plugged in" % (num(added / cons * 100.0), trim(added / cons * 100.0 / (h * 60.0), 1)))
        return
    # trip
    if not a.distance:
        die("ev trip needs --distance")
    cons, notes = _consumption(a)
    per_km = cons / 100.0
    first = a.battery * (a.start - a.floor) / 100.0 / per_km
    later = a.battery * (a.to - a.floor) / 100.0 / per_km
    if first <= 0 or later <= 0:
        die("the start and charge-to levels must be above --floor")
    rec("TRIP", "%s km at %s kWh/100 km: %s kWh for the whole way [estimate]" % (num(a.distance), trim(cons, 1), trim(a.distance * per_km, 1)))
    for n in notes:
        more(n)
    arrive_need = a.battery * (a.arrive - a.floor) / 100.0 / per_km if a.arrive > a.floor else 0.0
    rows, done, soc, total_h, grid_total, stop = [], 0.0, a.start, 0.0, 0.0, 0
    while True:
        reach = a.battery * (soc - a.floor) / 100.0 / per_km
        remaining = a.distance - done
        end_soc = soc - remaining * per_km / a.battery * 100.0
        if end_soc >= a.arrive - 1e-9:
            rows.append(("drive", "%s km" % num(remaining), "arrive with %s%%" % trim(end_soc, 0), ""))
            break
        stop += 1
        if stop > 40:
            die("more than 40 stops: check the numbers")
        done += reach
        remaining = a.distance - done
        need_soc = a.floor + (remaining * per_km / a.battery * 100.0) + max(0.0, a.arrive - a.floor)
        target = min(a.to, need_soc) if need_soc <= a.to else a.to
        h = charge_time_h(a.battery, a.floor, target, power)
        added = a.battery * (target - a.floor) / 100.0
        grid_total += added / (1.0 - loss / 100.0)
        total_h += h
        rows.append(("drive", "%s km" % num(reach), "down to %s%%" % trim(a.floor, 0), "at km %s" % num(done)))
        rows.append(("stop %d" % stop, "+%s kWh" % trim(added, 1), "%s%% -> %s%%" % (trim(a.floor, 0), trim(target, 0)), fmt_hm(h)))
        soc = target
    table(rows, indent=2)
    rec("STOPS", "%d, %s plugged in in total [estimate]" % (stop, fmt_hm(total_h)))
    if a.price and grid_total:
        rec("COST", "%s for %s kWh on the road at %s per kWh (the charge you left with is extra)" % (
            num(grid_total * a.price, 2), trim(grid_total, 1), trim(a.price, 2)))
    rec("NOTE", "check that chargers exist where the stops fall; cold packs charge slower than this model")


# ---- fuel

def cmd_fuel(a):
    if a.distance <= 0:
        die("--distance must be positive")
    dist = a.distance * (2 if a.ret else 1)
    given = [x for x in (a.l_100, a.mpg_us, a.mpg_uk, a.kwh_100) if x]
    look_up = ("look up its official combined figure (WLTP in Europe, NEDC for older cars, EPA in the US) and pass it with --l-100 or --kwh-100, and "
               "--source to say where it came from")
    est = None
    if len(given) > 1:
        die("give exactly one of --l-100, --mpg-us, --mpg-uk or --kwh-100")
    if not given:
        if a.kg is None:
            if a.car:
                die("no consumption figure for %s: %s; or give its mass with --kg for a rough model" % (a.car, look_up))
            die("give exactly one of --l-100, --mpg-us, --mpg-uk or --kwh-100; or --kg, the car's mass, for a rough model")
        if not 200 <= a.kg <= 60000:
            die("--kg is the mass as it drives, car and people and load, between 200 and 60,000")
        if not 20 <= a.speed <= 250:
            die("--speed is the steady speed for the model, 20 to 250 km/h")
        cda = a.cda if a.cda is not None else a.cd * a.area
        if cda <= 0 or a.crr <= 0:
            die("drag and rolling resistance must be positive")
        est = estimate_use(a.fuel, a.kg, a.speed, cda, a.crr)
    elif a.fuel == "electric" and not a.kwh_100:
        die("an electric car's consumption is --kwh-100")
    people = max(1, a.people)
    tag = "estimated" if est else "checked: %s" % a.source if a.source else "derived"
    rec("TRIP", "%s km%s" % (num(dist), " there and back" if a.ret else ""))
    if a.car:
        rec("CAR", "%s [as named]" % a.car)
    if est:
        unit = "kWh/100 km" if a.fuel == "electric" else "l/100 km of %s" % a.fuel
        basis = ("the wheels get 77 to 79% of the energy on the highway" if a.fuel == "electric" else
                 "22 to 30% of a petrol car's fuel energy reaches the wheels on the highway"
                 + (", and a diesel goes 20 to 35% farther on a litre" if a.fuel == "diesel" else
                    ", and a litre of LPG holds less energy" if a.fuel == "lpg" else ""))
        rec("ESTIMATE", "%s %s, somewhere between %s and %s [estimated: a model, not a figure for this car - %s kg on a level road at "
                        "a steady %s km/h, drag area %s m2, rolling %s; %s (fueleconomy.gov, AFDC)]" % (
                            trim(est[1], 1), unit, trim(est[0], 1), trim(est[2], 1), num(a.kg), trim(a.speed, 0),
                            trim(a.cda if a.cda is not None else a.cd * a.area, 2), trim(a.crr, 3), basis))
        if a.fuel == "electric":
            a.kwh_100 = est[1]
        else:
            a.l_100 = est[1]
    elif a.kg is not None:
        more("--kg is not used: a consumption figure was given, and that beats the model")
    if a.kwh_100:
        kwh = dist * a.kwh_100 / 100.0
        rec("ENERGY", "%s kWh at %s kWh/100 km [%s]" % (trim(kwh, 1), trim(a.kwh_100, 1), tag))
        if a.price:
            cost = kwh * a.price
            rec("COST", "%s at %s per kWh%s" % (num(cost, 2), trim(a.price, 2), "" if people == 1 else ", %s each for %d" % (num(cost / people, 2), people)))
        if a.grid_co2 is not None:
            rec("CO2", "about %s kg at %s g per kWh of grid power [as given]" % (trim(kwh * a.grid_co2 / 1000.0, 1), trim(a.grid_co2, 0)))
        if est:
            rec("NEXT", "a real trip uses more than a steady road does, and an official figure beats this model: " + look_up)
        return
    if a.fuel == "electric":
        die("an electric car's consumption is --kwh-100")
    if a.mpg_us:
        l100 = 100.0 * L_PER_GAL_US / (a.mpg_us * KM_PER_MI)
    elif a.mpg_uk:
        l100 = 100.0 * L_PER_GAL_UK / (a.mpg_uk * KM_PER_MI)
    else:
        l100 = a.l_100
    litres = dist * l100 / 100.0
    rec("FUEL", "%s l of %s at %s l/100 km [%s]" % (trim(litres, 1), a.fuel, trim(l100, 1), tag))
    if a.price:
        cost = litres * a.price
        rec("COST", "%s at %s per litre%s" % (num(cost, 2), trim(a.price, 2), "" if people == 1 else ", %s each for %d" % (num(cost / people, 2), people)))
    co2 = litres * CO2_KG_PER_L[a.fuel]
    rec("CO2", "about %s kg from the exhaust (%s kg per litre of %s) [typical factor]%s" % (
        trim(co2, 0), trim(CO2_KG_PER_L[a.fuel], 1), a.fuel, "" if people == 1 else ", %s kg each" % trim(co2 / people, 0)))
    if a.tank:
        rec("TANK", "%s l goes ~%s km; this trip takes %s tank%s" % (
            trim(a.tank, 0), num(a.tank / l100 * 100.0), trim(litres / a.tank, 1), "" if abs(litres / a.tank - 1) < 0.05 else "s"))
    if est:
        rec("NEXT", "a real trip uses more than a steady road does, and an official figure beats this model: " + look_up)


def register(sub):
    p = command(sub, "energy", "range", cmd_range, "FIRN-01 lore range after Veil use and distance (the quick budget)",
                ["range --veil-full 2 --distance 420", "range --km-left 600 --veil-partial 8"])
    p.add_argument("--km-left", type=float, help="lore: range left (default: the full 1,500 km)")
    p.add_argument("--veil-full", type=float, default=0, help="lore: minutes of full Veil")
    p.add_argument("--veil-partial", type=float, default=0, help="lore: minutes of one-face Veil")
    p.add_argument("--veil-rate", type=float, help="lore: km per minute of full Veil (default from lore.json)")
    p.add_argument("--distance", type=float, default=0, help="trip km")
    p.add_argument("--battery-kwh", type=float, help="real EV shortcut: usable pack size (see 'ev' for more)")
    p.add_argument("--soc", type=float, default=100, help="real EV: state of charge percent")
    p.add_argument("--kwh-per-100", type=float, help="real EV: consumption")
    p.add_argument("--penalty", type=float, default=0, help="real EV: percent lost to cold, speed, load")
    p.add_argument("--reserve", type=float, default=10, help="real EV: percent kept back (default 10)")

    p = command(sub, "energy", "ev", cmd_ev, "real electric cars: range with cold and speed, charging time and cost, charge stops on a trip",
                ["ev range --battery 77 --kwh-100 18.5 --temp -5 --distance 300",
                 "ev charge --battery 77 --start 10 --to 80 --kw 150 --price 2.19",
                 "ev trip --battery 77 --kwh-100 19 --distance 620 --kw 150 --temp 0"])
    p.add_argument("what", choices=["range", "charge", "trip"])
    p.add_argument("--battery", type=float, required=True, help="usable pack size, kWh")
    p.add_argument("--kwh-100", type=float, help="consumption, kWh per 100 km")
    p.add_argument("--soc", type=float, default=100.0, help="range: state of charge now, percent (default 100)")
    p.add_argument("--floor", type=float, default=10.0, help="lowest charge you will run down to, percent (default 10)")
    p.add_argument("--temp", type=float, help="outside temperature, C (adds a cold-weather penalty)")
    p.add_argument("--speed", type=float, help="cruising speed for this trip, km/h")
    p.add_argument("--ref-speed", type=float, help="speed the consumption figure was measured at, km/h")
    p.add_argument("--distance", type=float, help="trip length, km")
    p.add_argument("--start", type=float, default=100.0, help="charge/trip: starting state of charge, percent")
    p.add_argument("--to", type=float, default=80.0, help="charge/trip: charge up to this percent (default 80)")
    p.add_argument("--arrive", type=float, default=15.0, help="trip: arrive with at least this percent (default 15)")
    p.add_argument("--kw", type=float, default=150.0, help="charger power, kW (default 150)")
    p.add_argument("--car-max", type=float, help="the car's own peak charging power, kW")
    p.add_argument("--knee", type=float, default=50.0, help="charge percent where the taper starts (default 50)")
    p.add_argument("--tail", type=float, default=0.25, help="power at 100%% as a fraction of peak (default 0.25)")
    p.add_argument("--ac", action="store_true", help="AC charging: steady power, no taper")
    p.add_argument("--loss", type=float, help="charging loss percent (default 8 DC, 12 AC)")
    p.add_argument("--price", type=float, help="price per kWh")

    p = command(sub, "energy", "fuel", cmd_fuel, "fuel or energy for a trip, its cost, the split between people, and CO2",
                ["fuel --distance 342 --l-100 6.5 --price 6.49 --people 2", "fuel --distance 120 --mpg-us 32 --return",
                 "fuel --distance 342 --kwh-100 18 --price 1.2",
                 'fuel --distance 342 --l-100 4.6 --fuel diesel --car "Skoda Octavia 2019 1.6 TDI" --source "WLTP combined, the maker\'s data sheet"',
                 'fuel --distance 342 --kg 1450 --fuel diesel --speed 110 --car "a 2015 estate, 1.6 diesel"'])
    p.add_argument("--distance", type=float, required=True, help="one-way km")
    p.add_argument("--return", dest="ret", action="store_true", help="there and back")
    p.add_argument("--l-100", type=float, help="litres per 100 km")
    p.add_argument("--mpg-us", type=float, help="miles per US gallon")
    p.add_argument("--mpg-uk", type=float, help="miles per imperial gallon")
    p.add_argument("--kwh-100", type=float, help="electric: kWh per 100 km")
    p.add_argument("--fuel", choices=FUELS, default="petrol")
    p.add_argument("--car", help="whose car this is, or its make, model and year: a label on the record")
    p.add_argument("--source", help="where the consumption figure came from: it is then tagged as checked")
    p.add_argument("--kg", type=float, help="no figure to hand: the mass as it drives, kg, for a rough model at a steady speed")
    p.add_argument("--speed", type=float, default=90.0, help="with --kg: the steady speed, km/h (default 90)")
    p.add_argument("--cd", type=float, default=0.30, help="with --kg: drag coefficient (default 0.30)")
    p.add_argument("--area", type=float, default=2.2, help="with --kg: frontal area, m2 (default 2.2)")
    p.add_argument("--cda", type=float, help="with --kg: drag area Cd x A, m2 (instead of --cd and --area)")
    p.add_argument("--crr", type=float, default=0.012, help="with --kg: rolling resistance coefficient (default 0.012)")
    p.add_argument("--price", type=float, help="price per litre (or per kWh)")
    p.add_argument("--people", type=int, default=1, help="split the cost between this many")
    p.add_argument("--tank", type=float, help="tank size, litres")
    p.add_argument("--grid-co2", type=float, help="electric: grams of CO2 per kWh of grid power, if you know it")
