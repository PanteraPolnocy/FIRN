#!/usr/bin/env python3
"""FIRN field tools. Python 3.9+, standard library only, no network.

Usage:  python3 firn.py <command> [options]      (python on Windows)
        python3 firn.py tools                    every command, grouped, one line each
        python3 firn.py tools --find WORDS       the command for a job
        python3 firn.py <command> -h             options and examples for one command

Output is terse KEY value records, ready to pass on. Errors are one ERROR line on stderr, exit code 2.
Numbers carry their confidence: [derived] calculated, [estimate] a model, [lore] FIRN-01 canon,
[game rule] passed in by you from the current patch, [table] a reference table.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def cache_elsewhere(here):
    """Where a skill's folder is read-only, Python cannot keep its compiled files beside the scripts and compiles
    every module again on every call. Point it at a folder of our own in the temp directory instead.
    Left alone when Python was told not to write them, or already has a place for them. FIRN_NO_CACHE=1 turns it off."""
    if sys.dont_write_bytecode or getattr(sys, "pycache_prefix", None) or os.environ.get("FIRN_NO_CACHE"):
        return None
    if os.access(here, os.W_OK):
        return None
    base = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP") or ("" if os.name == "nt" else "/tmp")
    if not base or not os.path.isdir(base):
        return None
    uid = os.getuid() if hasattr(os, "getuid") else 0
    path = os.path.join(base, "firn-pycache-%d" % uid)
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.lstat(path)
    except OSError:
        return None
    if (st.st_mode & 0o170000) != 0o040000:
        return None                 # not a real folder: a link, or a file in the way
    if hasattr(os, "getuid") and (st.st_uid != uid or st.st_mode & 0o022):
        return None                 # someone else's folder, or one that others can write into
    sys.pycache_prefix = path
    return path


cache_elsewhere(HERE)

import firnlib  # noqa: E402,F401
from firnlib import core, index  # noqa: E402

_NEG = re.compile(r"^-\d")
_NUM = re.compile(r"^-\d+(\.\d+)?$")


def protect(argv):
    """Arguments such as -33.87,151.21 or -2h start with a minus but are values, not options.
    So are the weather groups of a METAR given without quotes (-SN, -SHRA)."""
    out = [("@" + t) if (_NEG.match(t) and not _NUM.match(t)) else t for t in argv]
    if out and out[0] == "metar":
        out = out[:1] + [("@" + t) if re.match(r"^-[A-Z]{2,}$", t) else t for t in out[1:]]
    return out


def build_parser(only=None):
    """The parser for every command, or for the commands of the modules named."""
    return index.build_parser(only)


def main(argv=None):
    core.setup_streams()
    core.SAID.clear()
    args = protect(list(sys.argv[1:] if argv is None else argv))
    if not args:
        args = ["tools"]
    try:
        # one call needs one module: load that, and leave the other two dozen on the shelf
        module = None if args[0].startswith("-") else index.module_of(args[0])
        parser = build_parser([module] if module else None)
        a = parser.parse_args(args)
        if not getattr(a, "func", None):
            parser.print_help()
            return 2
        a.func(a)
        sys.stdout.flush()
    except core.FirnError as e:
        sys.stdout.flush()
        sys.stderr.write("ERROR " + str(e) + "\n")
        return 2
    except BrokenPipeError:
        # the reader went away (firn.py ... | head): stop quietly, and keep the interpreter from complaining at exit
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
