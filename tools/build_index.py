"""Write src/scripts/data/commands.json: the index firn.py reads to load only the module a command needs,
and that 'tools --find' searches.

Run it after adding, renaming or re-describing a command, or changing the version:

  python tools/build_index.py            write the file
  python tools/build_index.py --check    write nothing; exit 1 if the file on disk is out of date

The build and the tests both run the check, so a stale index cannot ship.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
OUT = os.path.join(SRC, "scripts", "data", "commands.json")


def render(scripts=None):
    """The index for the scripts folder given (default: this repository's), as the text of the file."""
    scripts = scripts or os.path.join(SRC, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from firnlib import index
    data = index.collect()
    lines = ["{", '  "note": %s,' % json.dumps(data["note"]), '  "version": %s,' % json.dumps(data["version"]), '  "commands": [']
    rows = data["commands"]
    for n, row in enumerate(rows):
        lines.append("    %s%s" % (json.dumps(row, ensure_ascii=True), "," if n < len(rows) - 1 else ""))
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def current(path=OUT):
    try:
        with io.open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def main():
    text = render()
    if "--check" in sys.argv[1:]:
        if current() != text:
            sys.exit("src/scripts/data/commands.json is out of date: run  python tools/build_index.py")
        print("commands.json is up to date (%d commands)" % text.count('{"name"'))
        return
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote %s: %d commands, %.0f KB" % (os.path.relpath(OUT, ROOT), text.count('{"name"'), len(text) / 1024.0))


if __name__ == "__main__":
    main()
