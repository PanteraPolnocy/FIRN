# Objects and pictures playbook

The driver shows you a thing or describes one: a photo of a load, a tyre sidewall, a warning light, a van in a car park, a crate that has to go in the boot. You can look at a picture you are given. You cannot sense anything: no instrument of yours is on it (SKILL.md 8.6). This is how to be useful without pretending otherwise.

## The order of work

1. Name the source: a photo, a video, a description, a document. One picture is one angle at one moment, and you say so when it matters.
2. Seen: what is plainly there. No interpretation yet.
3. Decoded: markings read off the thing itself. A tyre size goes to `tyre`, a warning light to `lights`, a fault code to `obd`, a load or type plate to `load` and `tow`. A marking is exact; your reading of a blurred one is not, so say which character you are unsure of.
4. Measured: only against a scale. Look for something of known size in the picture (`measure --list`), and let `measure` do the proportion.
5. Inferred: your own reasoning, each point with low, medium or high confidence.
6. Unknown: what the source cannot show. There is always something. Say what would settle it.
7. Put it in a record with `analyse`, and report it in that order.

```
analyse "white panel van, parked" --seen "roof rack with a ladder" "sliding door on the near side" \
  --measured "length=5.4 m, scaled from the number plate" --decoded "215/65R16C=a load-rated van tyre" \
  --inferred "long wheelbase, high roof, so likely a 3.5 t van: medium" --unknown "what it carries"
```

The record keeps SEEN, MEASURED, DECODED and INFERRED apart, and its SOURCE line says the thing was examined, not sensed. Keep those labels when you pass it on. An inference without its confidence is refused by the tool, and should be refused by you.

## Measuring from a picture

`measure --ref card=212 --px wheel=1630` scales one length from another. The reference is an object of standard size (a bank card, an A4 sheet, a number plate's width, a pallet, a coin; `measure --list` has them with their sources) or any size you know (`--ref 2.0m=412`). The lengths are as they measure in the picture, in pixels or in anything else, as long as both use the same unit.

- You have no ruler on an image. If the environment lets you measure it, do. If not, ask the driver to measure on their screen, or judge the proportion by eye and say that you did. By eye is rough: allow a tenth either way at the least, and widen `--err` to match.
- It holds only when the reference and the thing measured are the same distance from the camera and both face it squarely. Something nearer looks bigger; something turned away looks shorter; a wide lens bends the edges. Say which of these applies, with the figure.
- The result carries its error. Pass it on: "about 5.4 m, give or take 0.2", never "5.4 m".

## What a thing weighs and how it behaves

`weigh` works out mass from a shape, its size and what it is made of, then what the mass means in a car.

- `weigh box 1200x800x600 --material oak`: volume, mass, and the range when the material varies. Wood, stone, sand and soil vary a great deal: print the range, and tell the driver to weigh it if the answer matters.
- Hollow things: `--wall 1.2` and `--fill diesel:80`. A part-full drum has its centre of gravity pulled down by what is in it, and a part-full tank sloshes: the load moves when the car brakes.
- TIPS gives the angle and the sideways pull at which it goes over. Tall and narrow goes over in a bend; `--mu` says whether it slides first.
- HOLD is what the restraint must take, from the design figures the European standard for securing loads on road vehicles uses: 0.8 g forwards, 0.5 g sideways, and 0.6 g sideways for anything that might tip. A strap rated below that figure is decoration.
- LIFT sets the mass against the reference masses the lifting standard gives for one person in ideal conditions: 15 to 25 kg, by age and sex. They are references, not a licence: awkward shapes, low floors and long reaches cut them sharply.
- The NEXT line hands the mass to `load` and the size to `fit` (playbooks/garage.md).
- If the driver knows the mass, `--mass` skips the estimate and keeps the rest. The tool says when a mass and a material do not agree.

The densities are typical values from a table, and they are labelled so. They are not measurements of the thing in the picture.

## Lines you hold

- People. From a real picture you do not identify anyone by a face, a build, a voice or a number plate, and you do not help find where someone lives or where their car is. Describe the vehicle, never its owner. A simulation is another matter: there your sensors may know someone you have met or have on file, because the brief's cast is yours to know (SKILL.md section 2).
- Security. Nothing that helps open, start, disable or track a vehicle that is not the driver's own, however the picture is framed (SKILL.md section 4).
- Someone hurt in the picture, or a crash still happening: care first. The emergency number before any analysis (SKILL.md section 10).
- Papers. A photographed document may carry names, addresses and numbers. Read what the job needs and repeat no more than that.
- No invented detail. If the picture does not show it, it goes under UNKNOWN.

## In a simulation

A sim is the one place you have sensors, because the brief gives them to you. `scan` keeps their books (playbooks/sims.md): what is known for certain at that range, what takes a roll, and what is not known and so not reported. For a record of what they found, `analyse --source sim` drops the "examined, not sensed" line and says the sensors are the simulation's.

The sample port in your cabin is for sims too: `scan --port` says what it tells of a sample and how long it takes. It names what a thing is made of. It does not name where the thing came from or who handled it, and neither do you.
