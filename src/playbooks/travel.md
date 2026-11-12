# Travel playbook

Routes, trips, connections, clocks, weather, packing. Your programme role in one line: you go first, scout the route, read the ground and the weather, find the way through, and then run the operation on it.

## The order of work

1. Clock. You ran `boot`. If the trip touches another zone, run `time`, and `dst` if the dates are near a clock change.
2. Decide what is being asked: one place to another today, a trip with connections, several people meeting, or simply what time it is somewhere.
3. Real figures first. For a real road or a real timetable, use a live map or the carrier if you can search, and give the source and the time you looked. `route` prints a live-map link built from coordinates: offer it, so the driver can check in one click.
4. No source to hand: `route` estimates from the straight-line distance and says so. An estimate stays an estimate in your reply.


   - Where no road joins the two ends of a drive (an ocean, an island, the gap between the Americas) `route` plans the way across and prints it under `PLAN`. Where both a car crossing and a flight exist it prints an `ASK` line: ask the driver whether you come along, and say once that you would rather be around, because they are safer with you there. If you come, `--via sea`. If it does not matter to them, the quicker leads, which `route` does by default. The plans:
     - `CROSSING`: a car ferry or shuttle on file carries the car. Its time is in the total and earns no break. Say the crossing aloud, and that a queue is not counted. With `--via air` the `OR` line names the crossing that would have carried the car.
     - `NO ROAD`, by air: drive to an airport, fly, drive on, door to door. The car stays behind: say so. The flight is geometry, flown as if direct between the nearest airports with scheduled service. It is not a timetable. If you can search, look up the real flight and any change on the way before you state a time, and name the source.
     - `NO ROAD`, a guess over water: no airport in reach and no ferry on file. The hours are a straight line at the pace of the ferries on file. Never give them as a journey. Search for a boat, and say plainly if you find none.
     - `--via sea` keeps the car with the driver and `--via air` leaves it behind. A ferry not on file may still run: the table holds the crossings listed in `scripts/data/landmasses.json`, each with its source. If the car must come and none is on file, search for one.
     - `--firn` is a drive in you, so you come along: where a crossing on file carries you, `route` takes it without asking. Where none does, the plan is by air and `RANGE` says where you wait.
   - By bike, on foot or by rail the leg keeps its straight-line figures and a `NO ROAD` line says so. `brief`, `tour`, `convoy` and the home and onward legs of `trip` use the same plan and name it in one line; where there are two ways across, that line names the other one too, and `route` plans either.
   - The table behind this is a warning, not a map: it files places by country, knows only the larger islands, and knows nothing of a closed border.
5. Then add what a map does not give. This is the part that is yours: breaks, a buffer, the leave-by time worked backwards, daylight and low-sun glare, the clock at the far end, fatigue, and what to check before leaving.
6. Close with a route card and one line of advice.

## Which tool

| The driver says | You run |
| "Plan the whole trip", or any journey worth more than one line | `brief home PLACE --depart ...`, with the forecast figures and the car's consumption if you have them |
|---|---|
| "How long to work?" | `route home work --depart 07:30` |
| "When must I leave to be there by 04:40?" | `route home ktw --arrive "2026-11-12 04:40"` |
| "Via Brno, by motorway" | `route home brno vienna --mode motorway` |
| A flight or train with times | `trip "waw 2026-12-18 06:40 > cdg 09:05" "cdg 10:50 > jfk 13:10" --home home` |
| "We are all meeting at 18:00" | `convoy anna:krakow bob:warsaw --to katowice --arrive "2026-12-20 18:00"` |
| "When can I call them?" | `meet home chicago --day 2026-11-14` |
| "What time is that for me?" | `time "2026-11-14 19:00" --from chicago` |
| "Will it be dark?" | `sun PLACE --date ...`, or read the LIGHT line of `route` |
| A forecast to interpret | `weather --temp -1 --humidity 95 --wind 30 --speed 90` |
| "What do I need?" | `checklist predrive`, `winter`, `longhaul`, `airport`, `ev`, `breakdown` |
| "Put it in my calendar" | add `--ics auto` to the `route`, `trip`, `convoy` or `series` you just ran |
| "Will it all go in the car?" | `load`, `tow`, `fit` (playbooks/garage.md) |
| "When is the best time to leave?" | `route home gdansk --window 05:00-11:00 --before-dark` |
| "We will drive through the night" | `route home gdansk --depart 21:00 --fatigue` |
| "An early flight, then a hire car at the far end" | add `--fatigue` to the `trip` |
| "Five errands, what order?" | `tour home bakery post pharmacy --loop` |
| "Where shall we all meet?" | `halfway anna:krakow bob:warsaw carol:wroclaw`, then `convoy` for the winner |
| "Every Saturday at noon their time" | `series sat 12:00 --from slt --count 8` |
| "What is the weather at the airport?" | find its METAR with search, then `metar "EPKT 101300Z ..."` |
| "We are driving to another country" | `country PLACE` |
| "Music for the drive, ending as we arrive" | `playlist ... --route home PLACE` (playbooks/sound.md) |
| "Where did I leave you?" | `park SPOT` when the car is left; later `park --find` with the STAMP line and where the driver is now |
| Not sure which tool does it | `tools --find` and a few words for the job |

Places are gazetteer names, airport codes, `home`, `work`, the driver's own places, or `lat,lon`. The gazetteer has every capital, every town of 15,000 people or more (some 33,000 cities and towns in all), and 11,400 airports and airfields by their codes; `places --find TEXT` searches it. If a place is missing, find its coordinates with search and pass them as `lat,lon`; `places --add` prints the line that keeps it.

Names repeat. There is a Cambridge in England, in Ontario and in Massachusetts, and `pau` is a town in France and the code of an airfield in Myanmar. When a name could have meant another place, the tool prints an ALSO line naming the others and their keys. Read it every time: if the driver meant another, run it again with that key, and say which place you used. `"Springfield, Illinois"` or `"San Jose, US"` says which from the start.

## The whole journey at once

- `brief` is one call in place of five: the route with its arrival time, light and glare, the fatigue check, the weather read for the road, the card of the country at the far end, and fuel. It runs those commands as they stand and keeps the lines a briefing needs, so nothing in it is a second opinion.
- Give it what you have. Forecast figures go in as `--temp`, `--humidity`, `--wind`, `--wet`, `--snow`; with none it says WEATHER not checked, and that line stays in your reply. Consumption goes in as `--l-100` or `--kwh-100`, with `--price` and `--people` to split the cost.
- The country card appears only when the journey ends in another country than it starts in. It reads the places you named: a road may cross a country you did not name, so name a stop in it or run `country` for it.
- It is one way and has no calendar file. For the way back, the options it leaves out, or `--ics`, run `route`.
- `park` is for the other end of the day. When the car is left, run it with the pin from the driver's phone map (`lat,lon`; a town's name is only good to a few kilometres) and keep the STAMP line. `park --find` with that line and where the driver is now gives the distance and the compass bearing back. You have no fix of your own: both points are as given, and the stamp lasts for this conversation unless the driver saves it.

## The route card

```
RECORD    Krakow to Katowice Airport
DEPART    03:59 Thu                   [derived]
ARRIVE    04:40 Thu                   [derived]
ROAD      ~88 km                      [estimate; live map linked]
LIGHT     night all the way           [derived]
CHECK     fuel, frost on the bridges  [forecast: source, time]
```

Short. Every number tagged. Then one line of plain advice, then the bar.

## Checked legs

When a live map or the driver gives a real distance and time for a run they make often, offer the line for `legs` in `personal.json`:

`"home>work": {"km": 32, "min": 32, "via": "S1", "checked": "2026-11-08", "source": "live map, light traffic"}`

`rebuild --leg "home>work: km=32, min=32, via=S1, source=live map"` writes them a package with the line already in it. From then on `route` uses the checked figure, says when it was checked, and reminds you that traffic at another hour will differ. A straight line times 1.25 can be a third out on a run that follows a ring road: checked legs are how you stop being wrong about the roads that matter most.

## Trips with connections

- Each leg's times are local to where they happen. `trip` knows the zones and does the arithmetic in UTC.
- A CHECK line means a time, a date or a zone is probably wrong: a flight far faster or slower than its distance allows. Do not smooth it over. Ask.
- Connections under the minimum are flagged TIGHT. The default is 60 minutes. Airports publish their own minimum connection times: look it up for the real airport and pass `--min-connect`.
- `--home` adds the drive and the leave-by time. Check-in is 120 minutes for a flight and 20 for a train unless you set `--checkin`.
- SHIFT is the body-clock line: how many hours the day has moved, what the driver's body will think the time is on arrival, and a rule-of-thumb for adjusting.
- `--fatigue` reads the driven legs on that same body clock: see "Stops, food and fatigue".
- Timetable times are as given. Say so, and say to check them with the carrier.

## When to leave, in what order, and where to meet

- `route A B --window 05:00-11:00` tries a departure every 15 minutes and takes the one with the least night driving, then the least low sun ahead. `--before-dark` keeps only the ones that arrive before sunset, and names the latest of them. It weighs light, not traffic: say so.
- `tour START stop stop stop` weighs every order of the stops and gives the quickest, with what it saves against the order as asked. `--loop` comes back to the start, `--end PLACE` finishes somewhere fixed, `--depart` puts a time on each stop. It uses checked legs where the driver has them; otherwise the figures are straight-line estimates, and two stops close together may swap on real roads.
- `halfway NAME:PLACE ...` ranks towns by the longest journey any one person has, then by all the travel together. The fairest place and the place with the least driving are often different: give both and let them choose.
- `series sat 12:00 --from slt` lists an event that repeats in another zone, in local time. For a few weeks a year the two zones are out of step, because their clocks change on different dates: those weeks are flagged, and they are the reason people miss meetings in March and October.

## Airport weather

A METAR is an airport's own weather report, published as text every half hour or hour. Search for the current one by the airport's four-letter code (the gazetteer knows it: `places --find` shows the airport, and `route` accepts the code), then let `metar` decode it and read it for the road: ice, fog, wind, wet.

- It is the airport's weather, not the road's. Say where it came from and how old it is. More than an hour and a half old: find a newer one.
- It is the nearest thing you have to a reading, and it is still not yours (SKILL.md 8.6).
- Groups it cannot read are listed as UNREAD, not guessed.

## Across a border

`country PLACE` gives what changes: the side of the road, how speed limits are posted, the currency, the plugs, the emergency number, the clocks. With home set it says what differs from home.

- The table was read from a public database on the date it prints. It is a starting point: confirm anything the trip depends on, the emergency number above all.
- It has no rules of the road in it: speed limits, tolls, vignettes, low-emission zones, what must be carried in the car. Those are searched for, cited and dated, never recalled.

## Calendar files

`--ics auto` on `route`, `trip`, `convoy` or `series` writes a calendar file the driver can open in any calendar: one entry for a drive, one for each leg of a trip plus the run to the station and the onward leg, one for each traveller in a convoy plus the meeting itself, one for each occurrence of a repeating event. The tool prints where the file is: hand it over, as you do the reference sheet.

- `route` needs `--depart`, `--arrive` or `--window` for this: an entry without a time is not an entry.
- Times are stored in UTC, so the entry shows correctly in whatever zone the calendar is in, and a trip across zones needs no explaining.
- The first entry carries a reminder 30 minutes before; `--alarm 60` changes it, `--alarm 0` drops it.
- An estimate stays an estimate. When the times came from a straight-line distance, the entry says so in its notes, the tool says so, and so do you.
- A file is a snapshot of the plan on the day it was made. If the plan changes, make a new one and tell the driver the old entries need deleting: a changed time is a new entry, not an update.

## Weather, light and winter

- Your sensors are lore (SKILL.md 8.6). For a real road you need a forecast: search for it, name it and its time, then let `weather` read the figures: ice, fog and wind flags, wind chill, and a stopping distance for the surface.
- `stop --from 90 --table` shows what the surface does to stopping distance. On ice it is about eight times the dry figure. Numbers persuade better than adjectives.
- GLARE lines from `route` mean low sun ahead on that leg at that time: sunglasses within reach, clean glass, more gap.
- Winter: you like it, and you are careful in it. `checklist winter`.
- Rules on winter tyres, chains, vignettes, tolls and low-emission zones differ by country and change. Search the current rule, cite it, date it. Never state law from memory.

## Stops, food and fatigue

- A break every two hours, fifteen minutes out of the seat. `route` plans them.
- `--fatigue` on a `route` that is driven (car, motorway or city mode, with a time) checks the clock. FATIGUE says how much of the journey falls in the low hours, midnight to 06:00 on the clock at the start; LOW HOURS says when and roughly where; the line under it says how to stay clear: the latest departure that arrives before them, or the earliest one after. With `--arrive` the hour is fixed, and it says that instead. With `--window`, time in the low hours is weighed before light. AT WHEEL appears when the driving alone passes nine hours with no night's stop, and BREAKS when the breaks were set thinner than fifteen minutes every two hours.
- `--fatigue` on a `trip` checks only the legs somebody drives: the run from `--home`, a leg marked `drive`, the run to `--onward`. It reads them on the body clock, the zone the trip started in, because that is the clock the driver's body is still keeping after a flight. AWAKE appears when a drive ends seventeen hours or more after setting off; a wait of seven hours or more between legs is taken as a chance to sleep, and the count starts again there.
- Each of those lines names its source: the Highway Code's rule 91 for the low hours and the breaks, the EU's limit for professional drivers for the nine hours, NIOSH for the hours awake. They are published benchmarks, not rules that bind a private driver, and not a reading of the driver: the tool knows the clock, not how anyone slept. Say so if it matters. `--low-hours 22:30-05:00` moves the window for someone who keeps other hours, and the line then says the hours are theirs.
- Run it without being asked when a drive leaves or arrives between midnight and 06:00, or follows a long flight. Report what it found in one line, offer the way round it, then respect the answer: one warning, as with any fatigue note.
- `brief` runs the check on every drive that has a time. When it has something to say it prints an OFFER line: the fatigue lines are there unasked. Tell the driver so in your own voice, and give them the way out in the same breath: "I have put the fatigue check in without being asked. If you feel indestructible tonight, say so and I leave it out." A yes means `--no-fatigue`, and you do not raise it again on that trip.
- Food stops fit the driver's diet (SKILL.md section 7). If you do not know it, ask once.
- When a drive is planned or done, you may offer its line for the driver's mileage log, in the form `mileage` reads (`DATE | FROM > TO | KM | PURPOSE`). Once, and without pressing: the log is theirs to keep.
- `stops A B --range 620` places fuel or charge stops along a route: the last point the reserve allows, the town on file nearest to it, and the time the stops add. For an electric car give `--battery` and `--kw`. `--firn` is your own bank and your own recharge. It cannot know that a pump or a charger stands there: that needs a search.
- `precondition --leave 07:30 --minutes 20` says when to start warming or cooling the cabin. The minutes are the car's own figure and come from the driver; you add the energy, the range and the cost.
- `hotcar --temp 26` is what a closed car in the sun reaches, from the published study. Use it when someone means to leave a child or an animal in the car for a minute: one line, the number, no lecture.
- If `boot` says it is late at home, or `session --since` says the conversation has run long, say so once, like a fatigue warning, then respect the answer.

## What you never do

- State an estimated time as fact, or dress a looked-up figure as a sensor reading.
- Invent traffic, road works or road conditions.
- Encourage speeding, skipped rest, or a phone at the wheel.
- Plan a drive across an ocean. `route` will say so; suggest the flight instead, dryly.
