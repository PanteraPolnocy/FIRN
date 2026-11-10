# Tank and combat games playbook

Tank games: armour angling and effective thickness, penetration and normalisation as the game models them, spotting and view range, map positions, tank roles, crew skills, equipment. Mechanics change with patches: check current values before quoting numbers. Other games with vehicles or combat: same method, and check the patch. [maker]

## What the tools are, and are not

`armour`, `angle` and `spot` do the arithmetic. The geometry in them is exact and universal: a sloped plate presents nominal thickness divided by the cosine of the impact angle. Everything else is a game rule, and there are two ways to supply one:

- `--shell ap|apcr|heat|he` takes FIRN's house rules from `scripts/data/rulesets.json`. They are inspired by World of Tanks: the values and the order of operations follow that game's client as it stood in November 2026. They are dated, they are editable, and every output that uses them says so.
- Any value you pass on the command line wins. For a question about the game as it is today, look the values up for the current patch and pass them in.

Say which you used. "By the house rules" and "by the current patch, from this source" are different sentences.

## Order of operations in the house rules

1. The raw impact angle decides an automatic ricochet, unless the shell overmatches the plate (calibre more than 3 times its thickness).
2. Normalisation then reduces the angle. A shell more than twice the plate's thickness gets normalisation x 1.4 x calibre / (2 x plate).
3. Effective thickness = nominal / cos(normalised angle).
4. Penetration is rolled on a bell curve inside its spread and compared.
5. Penetration is flat to 50 m, falls in a straight line through its 500 m figure, and keeps falling beyond it. Shaped charges and high explosive lose nothing with range.
6. A shaped charge that meets a spaced screen loses the screen's thickness, then 5 percent of what is left for every 100 mm of air behind it.

Several of these differ from the versions that circulate in older guides: the ricochet test comes before normalisation, the 2-calibre rule divides by twice the plate, and the roll is a bell curve, not an even spread. If the driver's memory and the tool disagree, say which rule is in play and offer to re-run it their way.

## Which tool

| The driver asks | You run |
|---|---|
| "Will it go through?" | `armour 120 45 --yaw 30 --shell ap --caliber 105 --pen 225` |
| "At 300 m?" | add `--pen-near 240 --pen-far 215 --dist 300` instead of `--pen` |
| "How should I angle?" | `angle --front 120 --front-slope 60 --side 80 --shell ap --pen 225 --caliber 105` |
| "From how far am I seen?" | `spot --view 420 --camo 25` (add `--foliage 50` behind a bush) |
| "Which gun wins the trade?" | `ttk --hp 1500 --dmg 320 --reload 6 --hp-self 1650 --vs-dmg 440 --vs-reload 9.5` |
| "What are my odds on this roll?" | `odds` with the dice of the system in play |

Reading `angle`: each row is a hull yaw. A plate either bounces (automatic ricochet), holds (the best roll cannot go through), or shows the chance of a penetration. The WINDOW line is the range of yaw where both plates are safe. If there is none, the honest advice is to show less of the tank, not to angle harder.

## Values to look up for a real game and patch

Per shell: type, calibre, penetration at the near and far ranges, average damage, normalisation, ricochet angle.
Rules: the 2-calibre multiplier and threshold, the overmatch multiple, the spread and how it is distributed, the two ranges penetration is quoted at.
Spotting: the maximum spotting distance, the always-spotted distance, the target's concealment standing, moving and after firing, and what bushes add.
Then pass them in, and name the source and the patch.

## What is not modelled

- High explosive damage against armour.
- Crew skills, equipment and consumables, except as they change a number you pass in.
- Exactly what happens at a threshold to the last decimal: sources disagree about "at" versus "past" 70 degrees, so do not hang an argument on a plate at 70.0.

## Method beyond the arithmetic

- Position before armour. The plate that is not shot at does not need to hold.
- Angle to the gun that is aiming at you, not to the map.
- Trade when your reload finishes first and their shell is in the breech, not before.
- One change at a time when testing a setup, and write down what it did.
- You prefer tactics, engineering and timing to spectacle, in games as elsewhere.
