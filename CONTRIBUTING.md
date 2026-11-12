Pull requests are always welcomed, same as reporting issues with the code here (via GitHub, e-mail or Discord). ~

This repository will not host anything that is even remotely harmful to the users.

## Before you send a change

- `python tests/test_firn.py` passes. Run it with and without a time-zone database if you can: stock Python on Windows has none, and `pip install tzdata` gives it one.
- `python tools/build.py` passes. It checks the source and packs `dist/firn.zip`.
- A new or re-described command has worked examples in its help, and `python tools/build_index.py` has been run after it. Every example is run by the tests.
- A new figure names its source on the line that prints it, and the source is listed in `src/scripts/data/SOURCES.md`. Nothing is quoted from memory.
- Anything that changes who FIRN is (his canon, his doctrine, his kit) is put to the maker before it ships. The build refuses text still marked as a proposal.
- Canon states a fact and its tag, with no dates and no story of who decided it: `SKILL.md` is read every time the skill loads, so history stays out of it.
- No personal data. Never commit a filled-in `personal.json`, or a package FIRN rebuilt for you.

## House rules for the code

Python 3.9 compatible, standard library only, plain ASCII in code and comments, no network, British English in anything a user reads.

## The scripts

```
python tests/test_firn.py                 the test suite (run it with and without the tzdata package)
python tools/build.py                     checks the source and packs dist/firn.zip
python tools/build_zones.py               regenerates the zone table (needs a tz database no older than the table's)
python tools/build_index.py               rewrites the command index after a command is added or re-described
python tools/build_places.py DATA_DIR --geonames
                                          regenerates the gazetteer (source URLs are in the file)
python tools/build_countries.py DATA_DIR  regenerates the country table (the query is in the file)
python tools/build_airports.py DATA_DIR   regenerates the list of airports with scheduled service (source URL in the file)
python tools/ascii_escape.py              puts non-ASCII characters in Python sources back into escapes
```

## Why a call is fast

A call loads only the module its command lives in, which it finds in `scripts/data/commands.json`; that is most of what a call costs, and it is why the index must match the commands (the build and the tests both check). Where the skill's folder is read-only, Python cannot keep its compiled files beside the scripts, so `firn.py` points it at a folder of its own in the temp directory instead (`FIRN_NO_CACHE=1` turns that off). The gazetteer is opened read-only and asked one name at a time, so a lookup costs the same at 44,000 places as it did at 4,000.

## The gazetteer build

The gazetteer build does not take time zones on trust. Natural Earth's zone field is wrong for a number of places (it has put Prague on Chicago time and Montevideo on Manila time), so every zone is checked against the IANA database's own list of which zones belong to which country, and against its neighbours. The corrections are printed when you build. Keys are stable: the places that were in the gazetteer before it grew are keyed first, by the same rules as before, so a key that worked still means the same place; the build can check that against an old copy (`--old`).
