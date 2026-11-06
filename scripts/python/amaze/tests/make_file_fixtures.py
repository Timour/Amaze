"""Build the committed fixtures under `USER=amaze hython`; exits 1 if one carries an identity."""
import os
import re
import shutil
import socket
import subprocess
import sys

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "files")
SCENES = os.path.join(HERE, "assets", "houdini")

NEUTRAL = b"amaze"
SCRATCH_ROOT = "/tmp/amaze-fixture-build"   # a literal path, not mkdtemp: a scene records its save dir, and macOS temp is per account

OPAQUE = (".sc", ".rat", ".abc", ".usd", ".usdc")   # formats that compress or tile their payload, so a byte scan proves nothing ▸r/author-stamp

CLEARED = {   # opaque files proven identity-free: same bytes written under two accounts ▸r/author-stamp
    "ramp.rat": "byte-identical under two accounts (2026-08-21)",
    "cube.abc": "differs by the same 2 timestamp bytes whether the account "
                "changes or not (2026-08-21)",
}

IMAGE_FORMATS = ("jpg", "tif", "tga", "bmp", "exr", "hdr", "rat")   # every image format the File section recognises, all written from one source PNG

EDGE_NAMES = (   # names that broke extension matching before; the name is the fixture, not the contents
    "UPPERCASE EXTENSION.PNG",     # matching is case-insensitive
    "with spaces.png",             # quoting in every path that joins it
    "wíth-únicøde.png",            # non-ASCII, NFD/NFC on macOS
)


def iconvert(src: str, dest: str) -> bool:
    tool = os.path.join(hou.getenv("HFS") or "", "bin", "iconvert")
    workdir = os.path.dirname(dest) or "."
    try:
        subprocess.run([tool, os.path.relpath(src, workdir),
                        os.path.basename(dest)],
                       check=True, cwd=workdir,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        print("  !! %s failed: %s" % (os.path.basename(dest), exc))
        return False
    return os.path.exists(dest)  # relative paths: iconvert stamps its own command line into the image it writes


def make_source_png(path: str) -> None:
    """A 32x32 ramp. Deterministic, ~1KB, depicts nothing."""
    from PySide6 import QtGui, QtCore
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    for x in range(32):
        for y in range(32):
            image.setPixelColor(x, y, QtGui.QColor(x * 8, y * 8, 128))
    image.save(path, "PNG")


GEO_NAMES = ("cube.bgeo", "cube.obj", "cube.abc")   # no `.bgeo.sc`: blosc compression hides the stamped host name from a scan ▸r/author-stamp

SCENE_NAMES = ("empty.hip", "empty.hiplc", "empty.hipnc")


def make_geometry(folder: str) -> None:
    """A box, written through Houdini so each format is genuine."""
    geo = hou.node("/obj").createNode("geo", "fixture_geo")
    box = geo.createNode("box")
    rop = geo.createNode("rop_geometry")
    rop.parm("soppath").set(box.path())
    try:
        for name in GEO_NAMES:
            rop.parm("sopoutput").set(os.path.join(folder, name))
            try:
                rop.parm("execute").pressButton()
            except hou.Error as exc:
                print("  !! %s failed: %s" % (name, exc))
    finally:
        geo.destroy()


def neutral_scene_vars(scratch: str) -> None:
    """Point JOB and POSE at a neutral `scratch`, since the scene records them verbatim."""
    for name in ("JOB", "POSE"):
        try:
            hou.hscript("set -g %s = '%s'" % (name, scratch))
        except hou.Error:
            pass


def neutral_scratch(name: str) -> str:
    """A build directory whose path names nobody, as a saved scene records it. ▸r/author-stamp"""
    path = os.path.join(SCRATCH_ROOT, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def stand_in(value: bytes) -> bytes:
    """The stand-in for one stamped identity, at the same byte length; never a prefix of `amaze`."""
    if len(value) < len(NEUTRAL):
        return b"x" * len(value)
    return NEUTRAL + b"-" * (len(value) - len(NEUTRAL))


def redact_identity(path: str) -> int:
    """Overwrite this machine's account and host names in `path`, same length; returns the count."""
    pattern = identity_pattern()
    if pattern is None:
        return 0
    with open(path, "rb") as handle:
        blob = handle.read()
    replaced = []

    def swap(match):
        replaced.append(match.group(0))
        return stand_in(match.group(0))

    out = pattern.sub(swap, blob)
    if replaced:
        with open(path, "wb") as handle:
            handle.write(out)
    return len(replaced)


def redact_written(paths) -> int:
    """Redact only the files this run wrote, never a directory with third-party assets in it."""
    return sum(redact_identity(p) for p in paths if os.path.isfile(p))


def make_scenes(folder: str) -> None:
    """All three scene extensions, each its own KIND_HIP label; saved in scratch, then moved."""
    scratch = neutral_scratch("scenes")
    neutral_scene_vars(scratch)
    for name in SCENE_NAMES:
        try:
            staged = os.path.join(scratch, name)
            hou.hipFile.save(staged, save_to_recent_files=False)
            shutil.move(staged, os.path.join(folder, name))
        except (hou.Error, OSError) as exc:
            print("  !! %s failed: %s" % (name, exc))
    shutil.rmtree(scratch, ignore_errors=True)


def real_account() -> str:
    """The real account name from the password database, as `USER` holds the stand-in."""
    try:
        import pwd                       # absent on Windows
    except ImportError:
        return os.environ.get("USERNAME") or ""
    return pwd.getpwuid(os.getuid()).pw_name


def identity_names() -> tuple:
    """This machine's real account and host names, longest first. ▸r/author-stamp"""
    names = {real_account(), socket.gethostname().split(".")[0]}
    return tuple(sorted((n for n in names if n and n.encode("utf-8") != NEUTRAL),
                        key=len, reverse=True))


def identity_pattern():
    """Those names with any dotted tail such as `.local`, any case, whole words; None if no names."""
    names = identity_names()
    if not names:
        return None
    alternatives = b"|".join(re.escape(n.encode("utf-8")) for n in names)
    return re.compile(
        rb"(?<![A-Za-z0-9_])(?:" + alternatives
        + rb")(?:\.[A-Za-z0-9-]+)*(?![A-Za-z0-9_])", re.IGNORECASE)


def make_materials_scene(folder: str) -> None:
    """A scene of two `materialbuilder` nodes under `/mat`, saved as Materials.hiplc. ▸r/material-flag"""
    scratch = neutral_scratch("materials")
    hou.hipFile.clear(suppress_save_prompt=True)
    neutral_scene_vars(scratch)   # after the clear, which puts every global variable back to the session's own
    mat = hou.node("/mat")
    for name in ("fixture_material_a", "fixture_material_b"):
        mat.createNode("materialbuilder", name)   # flagged Material by construction, wiring not required ▸r/material-flag
    staged = os.path.join(scratch, "Materials.hiplc")
    try:
        hou.hipFile.save(staged, save_to_recent_files=False)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        shutil.move(staged, os.path.join(folder, "Materials.hiplc"))
    except (hou.Error, OSError) as exc:
        print("  !! Materials.hiplc failed: %s" % exc)
    shutil.rmtree(scratch, ignore_errors=True)


PLACEHOLDERS = ("/someone", "/someone-else", "/projects")


def complaints(path: str) -> list:
    """What in `path` must not publish, judged by patterns of its own, never the redactor's."""
    home = re.compile(rb"(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])"   # both Windows slash styles, any case: Houdini writes C:/Users/<name> forward-slashed
                      rb"[A-Za-z0-9_.-]+"
                      rb"|/var/folders/[A-Za-z0-9_+-]{2}/[A-Za-z0-9_+-]{10,}",
                      re.IGNORECASE)
    stamped = re.compile(rb"(?<![A-Za-z0-9_])([A-Za-z0-9_.+-]{2,64})@"   # the host half must be dotted, or random pixel bytes around an `@` read as a stamp
                         rb"([A-Za-z0-9_-]{1,60}(?:\.[A-Za-z0-9_-]{2,20})+)"
                         rb"(?![A-Za-z0-9_])")
    literal = re.compile(
        rb"(?<![A-Za-z0-9_])(?:"
        + (b"|".join(re.escape(n.encode("utf-8"))
                     for n in identity_names()) or rb"(?!)")
        + rb")(?![A-Za-z0-9_])", re.IGNORECASE)
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError as exc:
        return ["unreadable, so unproven (%s)" % exc]
    found = []
    for match in home.finditer(blob):
        text = match.group(0).decode("utf-8", "replace")
        if not text.endswith(PLACEHOLDERS):
            found.append(text)
    for match in stamped.finditer(blob):
        if all(half and half == stand_in(half)   # both halves are stand-ins, so already redacted; checked per half, never by prefix
               for half in (match.group(1), match.group(2))):
            continue
        found.append(match.group(0).decode("utf-8", "replace"))
    found += [m.group(0).decode("utf-8", "replace")
              for m in literal.finditer(blob)]
    if (path.endswith(OPAQUE) and not found
            and os.path.basename(path) not in CLEARED):
        found.append("OPAQUE - a byte scan cannot see inside this format, "
                     "so it is unproven rather than clean")
    return sorted(set(found))


def verify_no_identity(paths) -> int:
    """Fail each written file carrying an identity, a home path or an unreadable payload; count them."""
    failed = 0
    for path in sorted(paths):
        if not os.path.isfile(path):
            print("  !! %s was never written" % os.path.basename(path))
            failed += 1
            continue
        for text in complaints(path):
            print("  !! %s carries %s" % (os.path.basename(path), text))
            failed += 1
    return failed


def main() -> int:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    nested = os.path.join(OUT, "nested")
    os.makedirs(nested)                       # per-location recursion

    png = os.path.join(OUT, "ramp.png")
    make_source_png(png)
    print("ramp.png")

    for ext in IMAGE_FORMATS:
        dest = os.path.join(OUT, "ramp." + ext)
        if iconvert(png, dest):
            print("ramp.%s" % ext)

    for name in EDGE_NAMES:
        shutil.copy2(png, os.path.join(OUT, name))
        print(name)

    make_geometry(OUT)
    make_scenes(OUT)
    make_materials_scene(SCENES)
    print("Materials.hiplc")

    with open(os.path.join(OUT, "readme.txt"), "w") as handle:   # KIND_OTHER: recognised by nothing, must still list with an OS icon
        handle.write("fixture\n")
    shutil.copy2(png, os.path.join(nested, "nested.png"))
    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)

    written = (   # every file the run intends, never a listdir, so a failed writer shows as never written
        [png]
        + [os.path.join(OUT, "ramp." + ext) for ext in IMAGE_FORMATS]
        + [os.path.join(OUT, name) for name in EDGE_NAMES]
        + [os.path.join(OUT, name) for name in GEO_NAMES + SCENE_NAMES]
        + [os.path.join(OUT, "readme.txt"),
           os.path.join(nested, "nested.png"),
           os.path.join(SCENES, "Materials.hiplc")]
    )
    present = [p for p in written if os.path.isfile(p)]
    total = sum(os.path.getsize(p) for p in present)
    print("\n%d of %d files, %.1f KB total"
          % (len(present), len(written), total / 1024.0))

    redacted = redact_written(written)
    print("redacted %d stamped identit%s"
          % (redacted, "y" if redacted == 1 else "ies"))
    carried = verify_no_identity(written)
    if carried:
        print("REFUSED: %d finding(s) - a fixture carries an account name, "
              "a machine name, a home directory, or a payload this cannot "
              "read; fix the writer above" % carried)
        return 1
    print("verified: no fixture carries an identity or a home directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
