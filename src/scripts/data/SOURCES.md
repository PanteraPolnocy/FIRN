# Where the data comes from

Every table the tools read is in this folder. Nothing is fetched while the tools run.

| File | What it holds | Source | Licence |
|---|---|---|---|
| `places.db` | capitals and cities | Natural Earth populated places, 10 m and 50 m (naturalearthdata.com) | public domain |
| `places.db` | towns of 15,000 people or more | GeoNames, cities15000 (geonames.org) | CC BY 4.0 |
| `places.db` | airports and their codes | OurAirports (ourairports.com) | public domain |
| `places.db`, `zones.json` | time zones | IANA Time Zone Database | public domain |
| `countries.json` | which side they drive on, currency, plugs, numbers | Wikidata | CC0 |
| `lsl.json` | the Second Life vehicle reference | the Second Life wiki and Linden Lab's published LSL definitions | compiled reference |
| `materials.json` | typical densities | handbook values; the fuel ranges are those of EN 228 and EN 590 | written for this skill |
| `references.json` | things of a standard size | the standard or the issuer named beside each entry | written for this skill |
| in the tools | limits for sound, loads and lifting | NIOSH (85 dB(A), 8 h); Directive 2003/10/EC; ITU-T H.870; EN 12195-1 as the European Commission's cargo securing guidelines quote it; ISO 11228-1 | named where each is printed |
| everything else | house rules, checklists, lore, the command index | written for this skill | MIT, with the code |

## GeoNames

The gazetteer contains data from GeoNames (https://www.geonames.org/), which is licensed under the Creative Commons Attribution 4.0 licence (https://creativecommons.org/licenses/by/4.0/). If you pass this package on, this credit must go with it.

What was changed: only towns that Natural Earth does not already list were taken; districts of cities and abandoned places were left out; each town keeps the name, coordinates, population and time zone GeoNames gives it, and each zone was checked against the tz database's list of the zones its country owns.

## Limits

City points are label points, good to a few kilometres; airports to a few hundred metres. Populations are as the sources give them and are used only to tell two towns of the same name apart. `tools/build_places.py` in the repository rebuilds the file and names every download.
