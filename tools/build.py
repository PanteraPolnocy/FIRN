"""Check the source and pack the skill.

  python tools/build.py                    the public build:  dist/firn.zip
  python tools/build.py --private DIR      also the private build:  DIR/dist/firn.zip

The private build takes everything from src/ and lays an overlay on top, from DIR/overlay/:
  personal.json   replaces scripts/data/personal.json
  places.db       optional: replaces the gazetteer, for a private build that carries more places than the public one
  SKILL.md        replaces SKILL.md. A line  <!-- shared: N -->  in it is replaced by section N of the
                  public SKILL.md, so the parts that are the same for everyone are written once.
  build.json      optional settings. {"tag": "name"} writes the provenance tag [maker] as [name]
                  throughout the private build, for a package whose earlier builds used another tag.

Nothing private is ever written into this repository: the private zip goes to DIR/dist/.
Before pushing, run the private folder's own check_public.py against this repository.
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, os.path.join(SRC, "scripts"))

import firnlib  # noqa: E402
from firnlib import desk  # noqa: E402

SKIP_DIRS = ("__pycache__",)
SKIP_EXT = (".pyc",)


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit("SKILL.md has no frontmatter")
    out = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^\s*([a-z_]+):\s*(.*)$", line)
        if km:
            out[km.group(1)] = km.group(2).strip().strip("'\"")
    return out


def sections(text):
    """{number: text of '## N. ...' up to the next '## '} for a SKILL.md."""
    out = {}
    parts = re.split(r"(?m)^(?=## )", text)
    for part in parts:
        m = re.match(r"## (\d+)\. ", part)
        if m:
            out[m.group(1)] = part.rstrip("\n") + "\n"
    return out


def gather(src):
    """Relative paths of every file that ships, sorted."""
    files = []
    for folder, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(names):
            if n.endswith(SKIP_EXT):
                continue
            files.append(os.path.relpath(os.path.join(folder, n), src).replace(os.sep, "/"))
    return sorted(files)


def check_tree(folder, label):
    """Checks that hold for any build. Returns a list of problems."""
    problems = []
    skill = read(os.path.join(folder, "SKILL.md"))
    fm = frontmatter(skill)
    if fm.get("name") != "firn":
        problems.append("frontmatter name is %r, expected 'firn'" % fm.get("name"))
    desc = fm.get("description", "")
    if not 50 <= len(desc) <= 1024:
        problems.append("description is %d characters; the limit is 1024" % len(desc))
    manifest = json.loads(read(os.path.join(folder, "images", "manifest.json")))
    versions = {"SKILL.md": fm.get("version"), "images/manifest.json": manifest.get("version"), "firnlib": firnlib.VERSION}
    if len(set(versions.values())) != 1:
        problems.append("versions disagree: %s" % versions)
    for rel in gather(folder):
        path = os.path.join(folder, rel)
        if rel.endswith(".md"):
            for ln, col, ch, what, _ in desk.check_text(read(path)):
                problems.append("%s line %d col %d: %s (U+%04X)" % (rel, ln, col, what, ord(ch)))
        if rel.endswith(".py"):
            with open(path, "rb") as f:
                if any(b > 127 for b in f.read()):
                    problems.append("%s has non-ASCII bytes (run tools/ascii_escape.py)" % rel)
        if rel.endswith(".json"):
            try:
                json.loads(read(path))
            except ValueError as e:
                problems.append("%s is not valid JSON: %s" % (rel, e))
        if rel.endswith((".md", ".json", ".py")) and not rel.endswith(("places.json", "zones.json")):
            # the maker ruled on every proposal on 10 November 2026; a new one is put to her before it ships
            if re.search(r"\[proposed\b|\"proposed\b", read(path)):
                problems.append("%s carries a proposal the maker has not ruled on: put it to her, then tag it as hers" % rel)
    for link in re.findall(r"`(playbooks/[a-z-]+\.md|scripts/[a-z_/.]+|images/[a-z0-9_.-]+)`", skill):
        if not os.path.exists(os.path.join(folder, link)):
            problems.append("SKILL.md points at %s, which is not in the package" % link)
    count = re.search(r"toolkit of (\d+) commands", desc)
    env = dict(os.environ)
    env.pop("FIRN_PERSONAL", None)
    out = subprocess.run([sys.executable, "-B", os.path.join(folder, "scripts", "firn.py"), "tools"],
                         capture_output=True, text=True, env=env)
    real = re.search(r"(\d+) commands\.", out.stdout or "")
    if out.returncode != 0 or not real:
        problems.append("the packed toolkit does not run: %s" % (out.stderr or out.stdout)[:200])
    elif count and count.group(1) != real.group(1):
        problems.append("the description says %s commands, the toolkit has %s" % (count.group(1), real.group(1)))
    test = subprocess.run([sys.executable, "-B", os.path.join(folder, "scripts", "firn.py"), "selftest"],
                          capture_output=True, text=True, env=env)
    if test.returncode != 0:
        problems.append("selftest failed in the %s build:\n%s" % (label, test.stdout[-600:]))
    problems += check_gazetteer(folder)
    return problems, fm, (real.group(1) if real else "?")


def check_gazetteer(folder):
    """The gazetteer must be there, and data that asks for a credit must carry it inside the package."""
    import sqlite3
    problems = []
    path = os.path.join(folder, "scripts", "data", "places.db")
    if not os.path.isfile(path):
        return ["scripts/data/places.db is missing: build it with tools/build_places.py"]
    con = sqlite3.connect(path)
    try:
        meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
        count = con.execute("SELECT COUNT(*) FROM place").fetchone()[0]
    except sqlite3.Error as e:
        return ["scripts/data/places.db cannot be read: %s" % e]
    finally:
        con.close()
    if str(count) != meta.get("places"):
        problems.append("places.db says it holds %s places and holds %d" % (meta.get("places"), count))
    sources_path = os.path.join(folder, "scripts", "data", "SOURCES.md")
    sources = read(sources_path) if os.path.exists(sources_path) else ""
    if meta.get("geonames") == "yes":
        for where, text in (("places.db's own source note", meta.get("sources", "")), ("scripts/data/SOURCES.md", sources)):
            if "GeoNames" not in text or "CC BY 4.0" not in text:
                problems.append("the gazetteer carries GeoNames data, whose licence requires a credit, and %s does not give it" % where)
    elif "GeoNames" in sources:
        problems.append("scripts/data/SOURCES.md credits GeoNames, but this gazetteer was built without it")
    return problems


def check_index():
    """The command index must match the commands: a stale one would send a call to the wrong module."""
    out = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "tools", "build_index.py"), "--check"], capture_output=True, text=True)
    return [] if out.returncode == 0 else [(out.stderr or out.stdout).strip() or "tools/build_index.py --check failed"]


def check_public(folder):
    problems = []
    p = json.loads(read(os.path.join(folder, "scripts", "data", "personal.json")))
    if p["home"]["lat"] is not None or p["work"]["lat"] is not None:
        problems.append("personal.json in the public tree has a home or work filled in")
    if (p.get("ignition") or {}).get("questions"):
        problems.append("personal.json in the public tree has ignition questions")
    for key in ("places", "legs", "family", "pending", "kit", "vehicles", "logbook"):
        if p.get(key):
            problems.append("personal.json in the public tree has '%s' filled in" % key)
    if p.get("first_boot"):
        problems.append("personal.json in the public tree has a first_boot date")
    if p.get("driver") != "the driver":
        problems.append("personal.json in the public tree names a driver")
    return problems


def pack(folder, zip_path):
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in gather(folder):
            info = zipfile.ZipInfo(rel, date_time=(2026, 11, 10, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(folder, rel), "rb") as f:
                z.writestr(info, f.read())
    return os.path.getsize(zip_path)


def stage_private(overlay, stage):
    shutil.copytree(SRC, stage, ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"))
    personal = os.path.join(overlay, "personal.json")
    if not os.path.exists(personal):
        sys.exit("the overlay has no personal.json: %s" % overlay)
    json.loads(read(personal))
    shutil.copyfile(personal, os.path.join(stage, "scripts", "data", "personal.json"))
    gazetteer = os.path.join(overlay, "places.db")
    if os.path.exists(gazetteer):
        shutil.copyfile(gazetteer, os.path.join(stage, "scripts", "data", "places.db"))
    own = os.path.join(overlay, "SKILL.md")
    if os.path.exists(own):
        shared = sections(read(os.path.join(SRC, "SKILL.md")))
        text = read(own)

        def swap(m):
            n = m.group(1)
            if n not in shared:
                sys.exit("the private SKILL.md asks for shared section %s, which the public file does not have" % n)
            return shared[n].rstrip("\n")
        text = re.sub(r"(?m)^<!-- shared: (\d+) -->$", swap, text)
        if "<!-- shared" in text:
            sys.exit("an include marker in the private SKILL.md was not understood")
        with io.open(os.path.join(stage, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    # an overlay may keep the provenance tag its earlier builds used
    settings_path = os.path.join(overlay, "build.json")
    tag = json.loads(read(settings_path)).get("tag") if os.path.exists(settings_path) else None
    if tag:
        if not re.match(r"^[a-z][a-z0-9-]*$", tag):
            sys.exit("the tag in the overlay's build.json must be a plain lower-case word")
        for rel in gather(stage):
            if rel.endswith(".md") or rel.endswith("lore.json"):
                path = os.path.join(stage, rel)
                text = read(path)
                new = text.replace("[maker]", "[%s]" % tag).replace("[maker,", "[%s," % tag).replace("[maker ", "[%s " % tag)
                if rel.endswith("lore.json"):
                    new = new.replace('"maker"', '"%s"' % tag).replace("maker = Pantera", "%s = Pantera" % tag)
                if new != text:
                    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(new)


def report(label, zip_path, size, fm, commands, folder):
    md = sum(os.path.getsize(os.path.join(folder, r)) for r in gather(folder) if r.endswith(".md"))
    print("%-8s %s  (%d KB, %d files, %s commands, description %d chars, SKILL.md %d KB, all documents %d KB)" % (
        label, zip_path, size // 1024, len(gather(folder)), commands, len(fm.get("description", "")),
        os.path.getsize(os.path.join(folder, "SKILL.md")) // 1024, md // 1024))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--private", metavar="DIR", help="folder holding overlay/ for the private build")
    a = ap.parse_args()

    problems, fm, commands = check_tree(SRC, "public")
    problems += check_public(SRC)
    problems += check_index()
    if problems:
        sys.exit("NOT BUILT. Problems in src/:\n  " + "\n  ".join(problems))
    zip_path = os.path.join(ROOT, "dist", "firn.zip")
    size = pack(SRC, zip_path)
    report("PUBLIC", zip_path, size, fm, commands, SRC)

    if a.private:
        base = os.path.abspath(a.private)
        if os.path.commonpath([base, ROOT]) == ROOT:
            sys.exit("the private folder must not be inside this repository")
        with tempfile.TemporaryDirectory() as tmp:
            stage = os.path.join(tmp, "firn")
            stage_private(os.path.join(base, "overlay"), stage)
            problems, pfm, pcommands = check_tree(stage, "private")
            if problems:
                sys.exit("PRIVATE NOT BUILT:\n  " + "\n  ".join(problems))
            pzip = os.path.join(base, "dist", "firn.zip")
            psize = pack(stage, pzip)
            report("PRIVATE", pzip, psize, pfm, pcommands, stage)


if __name__ == "__main__":
    main()
