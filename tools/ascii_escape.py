"""Rewrite non-ASCII characters in Python sources as escape sequences.

Pantera's rule: plain ASCII in code and comments. Editors and tools sometimes turn an escape
such as backslash-u-0142 into the character itself; this puts the escapes back.
Only safe because every non-ASCII character in these sources sits inside a string literal.

Usage: python tools/ascii_escape.py [folder ...]     (default: src/scripts tests tools)
"""
import io
import os
import sys

BS = chr(92)


def escape(text):
    out = []
    for c in text:
        n = ord(c)
        if n < 128:
            out.append(c)
        elif n < 0x10000:
            out.append("%su%04x" % (BS, n))
        else:
            out.append("%sU%08x" % (BS, n))
    return "".join(out)


def main(roots):
    changed = []
    for root in roots:
        for folder, _, files in os.walk(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with io.open(path, encoding="utf-8") as f:
                    text = f.read()
                fixed = escape(text)
                if fixed != text:
                    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(fixed)
                    changed.append(path)
    print("escaped: %s" % (", ".join(changed) if changed else "nothing to do"))


if __name__ == "__main__":
    main(sys.argv[1:] or ["src/scripts", "tests", "tools"])
