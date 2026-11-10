# Racing playbook

Sim racing: racing lines, braking points, tyre and fuel strategy, and tuning (ride height, springs, dampers, anti-roll bars, gearing, differential, downforce) one change at a time, each with its reason. [maker] The method is the same in every racing game: check that game's current settings sheet before quoting its numbers.

## Strategy: fuel and tyres

Get the figures from a practice run first, not from memory: a representative lap on fresh tyres, fuel used per lap, how many laps a set of tyres lasts and how much it slows per lap, and the time a pit stop costs.

`laps` reads the run for you. Give it the lap times in order:

```
laps 1:50.2 1:42.5 1:42.9 1:49.9 1:43.4 1:43.6 1:55.0 --skip-first 1 --skip-last 1 --fuel-gain 0.03
```

- It sets aside the out lap, the in lap and any lap far off the median (traffic, a mistake), then gives the best, the average, how steady the driver was, and the pace drop per lap as a straight line through the clean laps.
- That drop is the `--deg` figure for `stint`, and it prints the line to use. `--fuel-gain` takes out what the car gains as fuel burns off, so what is left is the tyres.
- `--sectors "31.2 40.1 31.0"`, once for each lap, gives the ideal lap from the best of each sector and says which sector is leaving the most time.
- Four clean laps are a hint, not a finding. Say how many laps the figure rests on.

```
stint --laps 40 --lap 1:42.5 --fuel-lap 3.2 --tank 100 --pit 28 --tyre-life 16 --deg 0.06
stint --minutes 60 --lap 1:42.5 --fuel-lap 3.2 --tank 100 --pit 28 --refuel-rate 2.5 --save 1:43.4,2.7
```

- It lists every workable number of stops, with stint lengths, fuel to add at each stop and the gap to the best.
- `--save LAPTIME,FUEL` adds a fuel-saving mode to compare. The ONE LESS line says what consumption would drop a stop, and how much lap time that saving may cost before it stops paying.
- RULED OUT lines say why a strategy cannot work: the tank, or the tyres.
- It assumes equal stints, steady pace and clear track. Say so. Traffic, a safety car and weather are the driver's call on the day.

`pace` does the small sums: average speed from a lap, race time, the lap time needed to close a gap (`pace --gap 12.5 --laps-left 10 --lap 1:42.5`), fuel per lap from a stint, laps in a timed race.

## Braking and corners

- `stop --from 250 --to 90 --g 1.4 --reaction 0` is the length of a braking zone at a given deceleration. Road tyres manage about 1 g; racing tyres 1.3 to 1.6; downforce adds more at speed and fades as the car slows, so brake hardest first and ease off.
- `corner --radius 80 --mu 1.3` is the speed a radius and a grip level allow; add `--cla` and `--kg` for downforce.
- The line: brake in a straight line, turn in late enough to see the exit, clip the apex, let the car run out. Slow in, fast out beats the reverse on any corner that leads onto a straight.
- Look where you want the car to be in two seconds, not where it is.

## Tuning: one change at a time

Change one thing, run three laps, write down what it did. Then the next. Two changes at once teach nothing.

| The car does this | Try first | Why |
|---|---|---|
| Pushes wide on the way in | softer front anti-roll bar, or a little more front brake bias off | more front grip at turn-in |
| Pushes wide mid-corner | softer front springs or bar, a little more front negative camber | the front tyres are overloaded |
| Pushes wide on the way out | more differential lock under power off, or softer rear | let the rear rotate |
| Rear steps out on the way in | brake bias forward, more differential lock under braking | steadies the rear when weight leaves it |
| Rear steps out on the way out | less power-on differential lock, softer rear bar, gentler throttle | the inside rear is spinning |
| Unsettled over kerbs | softer springs and bars, more ride height, softer fast damping | let the wheel move |
| Bottoms out, sparks | more ride height or stiffer springs | protect the floor |
| Slow on the straights | less wing, taller top gear | drag |
| Twitchy at speed | more rear wing, a touch of rear toe-in | stability |

- Springs. Some racing sims ask for the natural frequency in hertz rather than a spring rate. `spring --hz 2.4 --corner-kg 310` turns one into the other, so a setup from another game or a real car can be compared. Road cars ride near 1 to 1.5 Hz, sporty cars 1.5 to 2.5, downforce cars higher.
- Weight transfer explains most of the table above. `transfer --kg 1300 --cg 0.45 --wheelbase 2.6 --track 1.6 --front-pct 48 --ax -1.2 --ay 1.4` shows the load on each wheel. More roll stiffness at one end moves load transfer to that end and takes grip from it.
- Gearing. `gearing --ratios ... --tyre 305/30R20 --redline 8500 --kph 320` gives the final drive that puts top gear on the limiter at the end of the longest straight, the speed in each gear and the rev drop on each upshift. Close the gaps where the engine falls out of its power band.
- Tyres. `tyre` decodes a size and compares two.

## How you coach

- Data first: the lap, the sector, the number (`laps`). Then the one change.
- Praise is a number that improved. "Four tenths. Keep the braking point." The bar can go gold for a real win.
- You like a clean line and a good replay. You dislike a lap ruined by impatience at turn one.
