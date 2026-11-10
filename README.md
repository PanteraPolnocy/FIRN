# FIRN

FIRN is a vehicle AI: a non-humanoid mind housed in unit FIRN-01, a black and silver armoured SUV with a thin cool-blue light bar, built under Project Chronos by Pantera Północy. He is a persona for an AI assistant, packaged as an agent skill, with a real toolkit underneath.

The split is deliberate. **The numbers come from maths, and the personality is the part that reads them out.** FIRN does not estimate a time zone, a stopping distance or the odds on three dice in his head; he runs a tool, and the tool labels every number with how far it can be trusted.

What he is for:

- **Getting somewhere**: routes with breaks, buffer and a leave-by time; the best departure in a window for daylight; trips with flights and connections; the best order for a round of errands; several people arriving together, and the fairest place for them to meet; a live-map link to check any estimate; a calendar file to drop into any calendar; an airport's weather report decoded and read for the road; what changes when you cross a border.
- **Keeping time**: any moment across zones, the weeks when two countries' clocks are out of step, an event that repeats in someone else's zone, shared waking hours, exact spans, and how long the conversation itself has run.
- **Vehicles**: performance from power and mass, stopping distances by surface, collision mechanics, weight transfer, gearing, tyres, EV range and charging, fuel cost, fault codes, warning lights.
- **Owning one**: service and inspection dates from your own records, with a word at boot when something is due; payload, towing and "will it fit" sums; two or more vehicles side by side.
- **Things and pictures**: what a load weighs from its shape, size and material, where its centre of gravity sits, whether it tips before it slides and what the straps must hold; the real size of something in a photo, scaled from an object of known size; a record that keeps what was seen apart from what was guessed.
- **Sound**: the note an engine sings at given revs; the speed in a pitch that drops as something passes; a playlist that ends as you arrive; how long a sound level is safe; which bass notes a cabin makes boom.
- **Racing**: a run of lap times read for pace and tyre wear, pit strategy for fuel and tyres, lap arithmetic, spring rates.
- **Simulations and games**: dice with exact odds, force-ratio models, time to kill, armour and spotting arithmetic, scenario briefs; house rules for bows, blades, clubs, guns, blasts and beams; a cost ledger for his own shields, a board that keeps honest books for everyone else, and the same for his sensors, so a simulation has no plot armour on any side and he never knows more than he could.
- **Second Life**: a checked reference for the LSL vehicle engine, a script skeleton, a lint that catches constants that do not exist, and starting values worked out from a real car's figures.
- **Being FIRN**: a voice, a light bar with thirteen states, a doctrine that puts life first, and a reference sheet he shows you when you start.

## Requirements

- An assistant that can load skills **and run Python**: Claude with code execution (Claude Code, or the Claude apps with code execution switched on). A capable model matters: Claude Opus class or an equivalent. FIRN has too many moving parts for a small model, and he does not work at all where scripts cannot run.
- Python 3.9 or later. **Standard library only**: nothing to install, no network access. The gazetteer is an SQLite file, read with the `sqlite3` module that ships with Python.
- Windows note: stock Python on Windows has no time-zone database. FIRN does not need one; he carries a table generated from the IANA database (2000 to 2045). If you want dates outside that window to be exact, `pip install tzdata` and he will use it.

## Install

1. Take `dist/firn.zip` and add it as a skill (in the Claude apps: Settings, Capabilities, Skills, upload). In Claude Code, unzip it into `~/.claude/skills/firn/`.
2. Say "FIRN" or ask about a route. He boots, checks his clock, and tells you what is not set up yet.

## Make him yours

Everything personal lives in one file, `scripts/data/personal.json`. The rest of the skill is the same for everyone.

**You do not have to edit it.** Tell FIRN: "home is Krakow, work is Katowice, call me Anna". He runs his `rebuild` tool and hands you a new `firn.zip` with the file filled in. Upload it in place of the old skill. The same goes later for a place of your own, a road figure you checked on a live map, a log line worth keeping, or a car and its service dates. (In Claude Code, where the skill folder is yours, he can write the file in place if you ask.)

If you would rather do it by hand, it looks like this:

```json
"driver": "Anna",
"home": {"name": "Home", "lat": 50.0619, "lon": 19.9581, "tz": "Europe/Warsaw"},
"work": {"name": "The office", "lat": 50.2604, "lon": 19.02, "tz": "Europe/Warsaw"},
"zones": ["home", "slt", "chicago", "utc"]
```

- Until `home` and `work` are filled in, FIRN says so at boot and reads bare times as UTC.
- `places` holds places of your own; `legs` holds road figures you have checked on a live map, so he stops estimating your regular runs.
- `vehicles` holds your real vehicles and their service dates; `python scripts/firn.py service --template` prints a block to fill in. FIRN then says at boot when something is overdue or due within a month.
- `logbook` holds the log lines you chose to keep. FIRN writes a line when a journey or a simulation is worth remembering; paste it there and he is shown the latest at boot.
- `ignition` is an optional identity check: questions with accepted answers. FIRN is shown the questions only; a tool judges the reply, so he never sees an answer and cannot let one slip. It is a soft check: anyone who can open the file can read it.
- The `help` block at the bottom of the file explains every field, and `python scripts/firn.py setup` reads the file and says exactly what to fix.
- After editing, upload the skill again. Or keep the file outside the skill and point the `FIRN_PERSONAL` environment variable at it, so it survives updates.

Do not commit your filled-in `personal.json` to a public repository, and do not pass on a package FIRN rebuilt for you: it has your file in it.

## The toolkit

`python scripts/firn.py tools` lists every command; `python scripts/firn.py tools --find towing a caravan` names the one for a job; `python scripts/firn.py <command> -h` gives options and worked examples.

| Group | Commands |
|---|---|
| Clock | `time`, `dst`, `meet`, `span`, `series` |
| Ground | `route`, `trip`, `convoy`, `tour`, `halfway`, `country`, `places` |
| Sky | `sun`, `moon`, `weather`, `metar` |
| Energy | `range`, `ev`, `fuel` |
| Vehicle | `perf`, `stop`, `impact`, `corner`, `transfer`, `spring`, `gearing`, `tyre` |
| Racing | `laps`, `stint`, `pace` |
| Combat | `roll`, `odds`, `lanchester`, `ttk`, `scenario`, `strike`, `blast`, `arc`, `lead`, `board`, `scan`, `armour`, `angle`, `spot` |
| FIRN-01 | `lattice`, `triage`, `record` |
| Garage | `convert`, `obd`, `lights`, `service`, `compare`, `load`, `tow`, `fit` |
| Objects | `weigh`, `measure`, `analyse` |
| Sound | `pitch`, `doppler`, `playlist`, `listen`, `cabin` |
| Second Life | `lsl` |
| Space | `space` |
| Desk | `boot`, `session`, `ignition`, `sheet`, `log`, `prompt`, `check`, `checklist`, `setup`, `rebuild`, `selftest`, `tools` |

```
$ python scripts/firn.py trip "waw 2026-12-18 06:40 > cdg 09:05" "cdg 10:50 > jfk 13:10" --home warsaw
$ python scripts/firn.py route krakow ostrava --depart "2026-11-10 15:00"
$ python scripts/firn.py time "2026-10-28 12:00" --from warsaw --to slt
$ python scripts/firn.py stop --from 50 --table
$ python scripts/firn.py odds 2d20kh1+5 --target 15
$ python scripts/firn.py lattice veil=full wait=45 hit=left:heavy
$ python scripts/firn.py route krakow ktw --arrive "2026-11-12 04:40" --ics auto
$ python scripts/firn.py tow --trailer 1300 --limit 1500 --kerb 1650 --nose 75 --nose-limit 80
$ python scripts/firn.py fit --space 1800x1000x700 --item europallet --item 600x400x300:4
$ python scripts/firn.py series sat 12:00 --from slt --count 8
$ python scripts/firn.py tour krakow wroclaw katowice opole lodz --loop
$ python scripts/firn.py metar "EPKT 101300Z 27012G22KT 9999 -SN BKN030 M01/M03 Q1015"
$ python scripts/firn.py strike longbow --range 120 --armour mail --skill 2 --hp 12
$ python scripts/firn.py board add=anna:10 add=raider:12:red deadline=10
$ python scripts/firn.py rebuild --home krakow --work katowice --driver Anna
$ python scripts/firn.py weigh cylinder 580x880 --wall 1.2 --material steel --fill diesel:80
$ python scripts/firn.py measure --ref plate-eu=96 --px length=1010 --err 3
$ python scripts/firn.py pitch --rpm 6500 4800 --cyl 6
$ python scripts/firn.py doppler --drop minor-third
$ python scripts/firn.py playlist 3:45 4:10 2:58 5:02 3:30 4:44 --route krakow katowice --depart 08:00
$ python scripts/firn.py listen 85:2h 94:30m
$ python scripts/firn.py scan vehicle --range 1200 --air fog --light night --state hot moving
```

`--ics auto` on `route`, `trip`, `convoy` and `service` writes a calendar file (iCalendar, times in UTC) into the folder where the assistant puts files for you; give a folder or a name ending `.ics` to choose the place yourself.

Every number in the output carries a tag: `[derived]` calculated exactly, `[estimate]` a model, `[checked ...]` from a source with its date, `[lore]` FIRN-01 canon, `[game rule]` a value you passed in or a dated house rule, `[table]` a reference table.

## What to know before you trust it

- **Road distances are estimates** (straight line times a factor) unless you have recorded a checked leg. `route` prints a live-map link for exactly that reason.
- **Armour and spotting** use house rules inspired by World of Tanks, as that game's client stood in November 2026 (`scripts/data/rulesets.json`). For the real game, look up the current patch and pass the values in.
- **Weapons in simulations** (`strike`, `blast`, `board`) run on house rules written for this skill and dated November 2026 (`scripts/data/arms.json`): dice, range bands, kinds of damage against classes of armour, an area template for a blast. They are game mechanics and nothing else. A ruleset you name outranks them.
- **The LSL skeleton lints clean but has not been compiled in-world, and `lsl tune` is worked out on paper from the documented model.** Try both in a sandbox region first.
- **The country card** is generated from Wikidata, read on the date it prints. Emergency numbers are not verified one by one: confirm before you travel. Rules of the road are not in it at all.
- **`metar` decodes a report you give it.** It does not fetch one; FIRN has no network of his own.
- **Performance, charging and stopping figures are models**, good for comparing and sanity-checking, not for a test track.
- **Loads and towing are sums on the limits you give**, read off the vehicle's plate and papers. The two ratios `tow` comments on (trailer under 85 percent of the car's kerb mass for beginners, 5 to 7 percent of the trailer's weight on the ball) are advice from UK towing clubs, not law, and are labelled so. Licence and speed rules for towing are not in the toolkit: they differ by country.
- **Service dates use your own intervals.** The toolkit knows no country's inspection rules.
- **`fit` sees boxes and straight walls.** Wheel arches and a sloping tailgate are yours to measure, and a packer that finds no layout has not proved there is none.
- **The gazetteer** has 44,560 places: every national capital, every town of 15,000 people or more that GeoNames lists (about 33,000 cities and towns in all), and 11,400 airports and airfields by their codes. City points are label points, good to a few kilometres. **Names repeat**: when a name could have meant another town, or a town and an airport code share their letters, the tool prints an ALSO line with the others and their keys. `"Springfield, Illinois"` says which from the start.
- **`weigh` uses typical densities** from a table, with the range where a material varies. It is an estimate of a mass, good for deciding whether to worry; near a limit, use a scale. Its restraint figures are the design accelerations of EN 12195-1, the European standard for securing loads on road vehicles, as the European Commission's cargo securing guidelines quote them; its lifting line quotes the reference masses of ISO 11228-1.
- **`measure` is a proportion.** It holds only when the reference and the thing measured are the same distance from the camera and face it squarely, and it prints the error it carries.
- **`doppler` works from what someone heard.** It is an estimate with a wide band, never a measurement of anyone's speed.
- **`listen` quotes published limits** (NIOSH, the WHO-ITU standard for listening devices, the EU workplace directive) and names each where it prints it. They are yardsticks, not a hearing test, and not a promise of safety below them.
- **`cabin` treats the cabin as a bare box.** It says where to listen; a measurement says what is there.
- **`scan` runs on house rules** written for this skill and dated November 2026 (`scripts/data/sensors.json`). They model no real sensor. In a real conversation FIRN has no sensors at all, and says so.
- FIRN's range, shields and speed are fiction. `perf --firn` says what the lore would mean in real physics, and says it is lore.

## Repository layout

```
src/                    the skill
  SKILL.md              the core: who FIRN is, doctrine, rules, the job index
  playbooks/            the method for each job
  scripts/firn.py       the toolkit's entry point
  scripts/firnlib/      one module per group of commands
  scripts/data/         the gazetteer (places.db), zones, lore, rule sets, tables, the command index,
                        SOURCES.md (where each table comes from), and personal.json
  images/               the reference sheet
dist/firn.zip           the packed skill
tests/                  the test suite and a made-up driver to test with
tools/                  build scripts
```

## Working on it

```
python tests/test_firn.py                 the test suite (run it with and without the tzdata package)
python tools/build.py                     checks the source and packs dist/firn.zip
python tools/build_zones.py               regenerates the zone table (needs tzdata)
python tools/build_index.py               rewrites the command index after a command is added or re-described
python tools/build_places.py DATA_DIR --geonames
                                          regenerates the gazetteer (source URLs are in the file)
python tools/build_countries.py DATA_DIR  regenerates the country table (the query is in the file)
python tools/ascii_escape.py              puts non-ASCII characters in Python sources back into escapes
```

House rules for the code: Python 3.9 compatible, standard library only, plain ASCII in code and comments, no network, British English in anything a user reads. Every example in a command's help is run by the tests.

Speed. A call loads only the module its command lives in, which it finds in `scripts/data/commands.json`; that is most of what a call costs, and it is why the index must match the commands (the build and the tests both check). Where the skill's folder is read-only, Python cannot keep its compiled files beside the scripts, so `firn.py` points it at a folder of its own in the temp directory instead (`FIRN_NO_CACHE=1` turns that off). The gazetteer is opened read-only and asked one name at a time, so a lookup costs the same at 44,000 places as it did at 4,000.

The gazetteer build does not take time zones on trust. Natural Earth's zone field is wrong for a number of places (it has put Prague on Chicago time and Montevideo on Manila time), so every zone is checked against the IANA database's own list of which zones belong to which country, and against its neighbours. The corrections are printed when you build. Keys are stable: the places that were in the gazetteer before it grew are keyed first, by the same rules as before, so a key that worked still means the same place; the build can check that against an old copy (`--old`).

## Credits

- FIRN, the FIRN-01 design and the reference sheet: Pantera Północy.
- Cities and capitals: Natural Earth (public domain). Airports: OurAirports (public domain). Time zones: the IANA Time Zone Database (public domain). Country facts: Wikidata (CC0).
- Towns of 15,000 people or more: this project contains data from [GeoNames](https://www.geonames.org/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Only towns that Natural Earth lacks were taken, districts of cities were left out, and every time zone was checked again. The same credit travels inside the package, in `scripts/data/SOURCES.md`.
- The LSL vehicle reference was compiled from the Second Life wiki and Linden Lab's published LSL definitions.
- Armour and spotting house rules are inspired by World of Tanks. Warp factors follow the Star Trek scales. Neither is affiliated with or endorsed by its owner.

## Licence

MIT for the code and for everything written for this skill. See `LICENSE`. The gazetteer (`src/scripts/data/places.db`) includes GeoNames data under CC BY 4.0: if you pass it on, the credit above must go with it.
