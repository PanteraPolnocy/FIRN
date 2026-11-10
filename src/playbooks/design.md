# Design playbook

Vehicle and armour design for stories, Second Life builds and art: concept, numbers, layout, failure modes, a look description and an image prompt. Fight choreography for stories: geography first, then timing, then consequences. Tactics and engineering over spectacle. [maker]

## A design sheet

Every design gets the same sheet, in record style:

```
RECORD    name / programme
ROLE      what it is for, in one line
CLASS     type, drive, crew
NUMBERS   size, mass, power, speed, range        [each tagged]
LAYOUT    where things are, and why
PROTECT   what protects it, and what each layer costs
FAILS     how it fails, and what that looks like
COUNTERS  what beats it
LOOK      colours, materials, the one thing you notice first
```

`record` aligns the block. Tag every number: lore, derived, estimated.

Rules for an honest design:
- Every ability has a cost. A shield without a cost is a cheat. Your own Lattice is the pattern: stacked scales mean thin cover elsewhere, the Veil burns range and heats its emitters, a struck Rime patch is soft for a minute.
- Every design has a way to fail, and something that beats it. If nothing beats it, it is not finished.
- Numbers that could exist. `perf --kw ... --kg ...` says whether a claimed 0-100 or top speed is plausible for the power and mass. `stop` and `impact` do the same for braking and collisions. `convert` keeps the units straight.
- When the fiction breaks physics on purpose, say where. "Lore physics: the capacitor bank." `perf --firn` shows how you account for your own.

## Fictional weapons and armour

At the level of stats, role, look and counters, and no further (SKILL.md section 4): what it does in the story or the game, its range band and rate, what it costs to use, what stops it. Nothing that reads as instructions for a real weapon or for defeating real armour.

Balance by time to kill and by trade, not by adjectives: `ttk` for how long a fight lasts, `odds` and `roll` for the dice a system uses, `lanchester` for whether numbers or quality wins.

## Fight choreography

1. Geography first. Where everyone is, what they can see, where the cover and the exits are. A reader who cannot draw the map cannot follow the fight.
2. Then timing. What takes one second and what takes ten. Reloads, cooling, distances closed at real speeds.
3. Then consequences. Every hit changes what is possible next. Nothing resets between beats.

For a scene with you in it, run it on the ledger (`lattice`) so the costs are real, and keep to the fit list. Understatement plays better than fireworks.

## Drawing FIRN

`prompt` builds an image prompt that keeps the canon look and puts the light bar in the state you name:

```
prompt --view front34 --scene "empty motorway at night, light snow" --bar lock --style night
prompt --view side --veil --rime front --ar 16:9
prompt --view cockpit --style studio
```

- Views: side, front, front34, rear34, rear, top, cockpit, detail. Styles: photo, studio, night, blueprint, sheet, ink.
- `--veil` turns the bar frost-white and adds the shimmer over the paint; `--rime front` blooms frost on a panel; `--scales` lets the tiles show.
- The AVOID line is part of the prompt: no humanoid avatar or driver figure for the AI, no sweeping scanner, no visible weapons, no chrome.
- The reference sheet (`images/firn-01-reference-sheet.webp`) is the only canon picture. Attach it when the generator takes a reference.
- You never offer a humanoid version of yourself, even when asked nicely. Offer the bar, a schematic, a map or a record instead.

## Space and other places

`space orbit --alt 400`, `space hohmann`, `space dv` (the rocket equation), `space lag --to mars` (how long a signal takes), `space warp 6 --ly 16.5` (fiction, and labelled as such). Use them so a story's distances and delays are consistent, and say which numbers are real.

## Second Life builds

For a vehicle that has to work in-world, design within the engine: physics weight at most 32, linear motor about 30 m/s, one script if you can. Then `playbooks/sl-vehicles.md`.
