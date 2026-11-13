# Where the data comes from

Every table the tools read is in this folder. Nothing is fetched while the tools run.

| File | What it holds | Source | Licence |
|---|---|---|---|
| `places.db` | capitals and cities | Natural Earth populated places, 10 m and 50 m (naturalearthdata.com) | public domain |
| `places.db` | towns of 15,000 people or more | GeoNames, cities15000 (geonames.org) | CC BY 4.0 |
| `places.db` | airports and their codes | OurAirports (ourairports.com) | public domain |
| `places.db`, `zones.json` | time zones | IANA Time Zone Database | public domain |
| `countries.json` | which side they drive on, currency, plugs, numbers | Wikidata | CC0 |
| `cabin_heat.json` | how far a closed car's air rises above the outside temperature in the sun | Jan Null, San Jose State University, "Vehicle Heating Dynamics" (noheatstroke.org); published as McLaren, Null and Quinn, Pediatrics 2005 | published figures, quoted with their source |
| `airports.json` | which gazetteer airports have scheduled airline service, and which are large | OurAirports (ourairports.com) | public domain |
| `landmasses.json` | which land mass a place is on, where a road does not join two of them, and thirteen car crossings | land masses written for this skill from the map; each crossing from the page named beside it in the file (LeShuttle, Direct Ferries, a Stena Line timetable, Traghettilines, Interislander, AFerry, britishcolumbia.com, Spirit of Tasmania, Marine Atlantic); the break in the Pan-American Highway from Wikipedia, "Darien Gap" | written for this skill |
| `lsl.json` | the Second Life vehicle reference | the Second Life wiki and Linden Lab's published LSL definitions | compiled reference |
| `materials.json` | typical densities | handbook values; the fuel ranges are those of EN 228 and EN 590 | written for this skill |
| `references.json` | things of a standard size | the standard or the issuer named beside each entry | written for this skill |
| in the tools | limits for sound, loads and lifting | NIOSH (85 dB(A), 8 h); Directive 2003/10/EC; ITU-T H.870; EN 12195-1 as the European Commission's cargo securing guidelines quote it; ISO 11228-1 | named where each is printed |
| in the tools | figures for driver fatigue | the Highway Code (Great Britain), rule 91: the low hours, breaks; Regulation (EC) No 561/2006, article 6: a professional driver's nine hours a day; NIOSH: 17 and 24 hours awake | named where each is printed |
| in the tools | what g does to the people aboard, for `jump` | StatPearls, "G-LOC" (Whinnery and Forster's 888 episodes: none below 4.7 g, none sooner than 5 s); Indian Journal of Aerospace Medicine, "Ejection in unusual aircraft attitude: a case report" (a current ejection seat gives 12 to 14 g); Stemper and others, "Biomechanical tolerance of whole lumbar spines in straightened posture subjected to axial acceleration", Journal of Orthopaedic Research 36(6) (even odds of injury at 16 g, 95% interval 13 to 19) | named where each is printed |
| in the tools | the model behind `fuel --kg`, for a car with no figure to hand | US DOE Alternative Fuels Data Center, "Fuel Properties Comparison" (lower heating values of petrol, diesel and LPG); fueleconomy.gov, "Where the Energy Goes: Gasoline Vehicles" (22 to 30% of the fuel's energy reaches the wheels in highway driving) and "Electric Cars" (77 to 79%, with the energy won back in braking); fueleconomy.gov, "Diesel Vehicles" (20 to 35% farther on a gallon than a petrol counterpart) | US government works |
| everything else | house rules, checklists, lore, the command index | written for this skill | MIT, with the code |

## GeoNames

The gazetteer contains data from GeoNames (https://www.geonames.org/), which is licensed under the Creative Commons Attribution 4.0 licence (https://creativecommons.org/licenses/by/4.0/). If you pass this package on, this credit must go with it.

What was changed: only towns that Natural Earth does not already list were taken; districts of cities and abandoned places were left out; each town keeps the name, coordinates, population and time zone GeoNames gives it, and each zone was checked against the tz database's list of the zones its country owns.

## Limits

City points are label points, good to a few kilometres; airports to a few hundred metres. Populations are as the sources give them and are used only to tell two towns of the same name apart. `tools/build_places.py` in the repository rebuilds the file and names every download.
