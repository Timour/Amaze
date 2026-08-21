"""Build the tracked fixture assets - one tiny file per KIND, plus the scene test_renders loads - as `USER=amaze hython make_file_fixtures.py`, the neutral account being something Houdini resolves at startup and this script cannot set for itself (▸r/author-stamp); the output is COMMITTED so the suite generates nothing at test time, and this exits 1 naming the file if anything it wrote carries an account name, a machine name or a home directory."""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "files")
SCENES = os.path.join(HERE, "assets", "houdini")

NEUTRAL = b"amaze"

IMAGE_FORMATS = ("jpg", "tif", "tga", "bmp", "exr", "hdr", "rat")   # every image format the File section recognises, written from one source PNG so a decode difference is the only thing that can differ

EDGE_NAMES = (   # names that have broken extension matching before - contents do not matter, the NAME is the fixture
    "UPPERCASE EXTENSION.PNG",     # matching is case-insensitive
    "with spaces.png",             # quoting in every path that joins it
    "wíth-únicøde.png",            # non-ASCII, NFD/NFC on macOS
)


def iconvert(src: str, dest: str) -> bool:
    tool = os.path.join(hou.getenv("HFS") or "", "bin", "iconvert")
    try:
        subprocess.run([tool, os.path.basename(src), os.path.basename(dest)],
                       check=True, cwd=os.path.dirname(dest) or ".",
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        print("  !! %s failed: %s" % (os.path.basename(dest), exc))
        return False
    return os.path.exists(dest)  # BASENAMES from the destination directory: iconvert records its own command line inside the image it writes, so absolute paths here publish the operator's home directory (verify_no_home_paths is the backstop)


def make_source_png(path: str) -> None:
    """A 32x32 ramp. Deterministic, ~1KB, depicts nothing."""
    from PySide6 import QtGui, QtCore
    image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_RGB32)
    for x in range(32):
        for y in range(32):
            image.setPixelColor(x, y, QtGui.QColor(x * 8, y * 8, 128))
    image.save(path, "PNG")


def make_geometry(folder: str) -> None:
    """A box, written through Houdini so each format is genuine."""
    geo = hou.node("/obj").createNode("geo", "fixture_geo")
    box = geo.createNode("box")
    rop = geo.createNode("rop_geometry")
    rop.parm("soppath").set(box.path())
    try:
        for name in ("cube.bgeo.sc", "cube.bgeo", "cube.obj", "cube.abc"):
            rop.parm("sopoutput").set(os.path.join(folder, name))
            try:
                rop.parm("execute").pressButton()
            except hou.Error as exc:
                print("  !! %s failed: %s" % (name, exc))
    finally:
        geo.destroy()


def neutral_scene_vars(scratch: str) -> None:
    """Point every path variable Houdini stamps into a saved scene at `scratch` - HIP and HIPFILE follow the save location, but JOB and POSE are inherited from the session and carry the operator's home directory into the file otherwise."""
    for name in ("JOB", "POSE"):
        try:
            hou.hscript("set -g %s = '%s'" % (name, scratch))
        except hou.Error:
            pass


def stand_in(value: bytes) -> bytes:
    """The replacement for one stamped identity, at the SAME byte length - which is the whole constraint, a shorter one being a corrupt file. ▸r/author-stamp"""
    if len(value) <= len(NEUTRAL):
        return NEUTRAL[:len(value)]
    return NEUTRAL + b"-" * (len(value) - len(NEUTRAL))


def redact_identity(path: str) -> int:
    """Overwrite this machine's account and host names wherever `path` carries them, in place and at the same byte length. Returns how many were replaced. ▸r/author-stamp"""
    with open(path, "rb") as handle:
        blob = handle.read()
    replaced = []
    def swap(match):
        replaced.append(match.group(0))
        return stand_in(match.group(0))
    out = identity_pattern().sub(swap, blob)
    if replaced:
        with open(path, "wb") as handle:
            handle.write(out)
    return len(replaced)


def redact_tree(folder: str) -> int:
    total = 0
    for root, _dirs, names in os.walk(folder):
        for name in names:
            total += redact_identity(os.path.join(root, name))
    return total


def make_scenes(folder: str) -> None:
    """All three scene extensions - each is its own KIND_HIP label ('Hiplc', not 'HIPLC'), and matched_extension picks the longest. Saved in a scratch directory and moved, because the save location is written INTO the file."""
    scratch = tempfile.mkdtemp(prefix="amaze_fixture_scene_")
    neutral_scene_vars(scratch)
    for name in ("empty.hip", "empty.hiplc", "empty.hipnc"):
        try:
            staged = os.path.join(scratch, name)
            hou.hipFile.save(staged, save_to_recent_files=False)
            shutil.move(staged, os.path.join(folder, name))
        except (hou.Error, OSError) as exc:
            print("  !! %s failed: %s" % (name, exc))
    shutil.rmtree(scratch, ignore_errors=True)


def real_account() -> str:
    """This machine's account name, from the password database rather than `USER` - a run passes a neutral one and the environment would answer with the stand-in. ▸r/author-stamp"""
    try:
        import pwd                       # absent on Windows
    except ImportError:
        return os.environ.get("USERNAME") or ""
    return pwd.getpwuid(os.getuid()).pw_name


def identity_pattern():
    """This machine's real account and host names, with any dotted tail a writer appends and in any case - Houdini stamps `amaze----------` where `socket.gethostname()` answers `amaze----`."""
    names = {real_account(), socket.gethostname().split(".")[0]}
    alternatives = b"|".join(
        re.escape(name.encode("utf-8"))
        for name in sorted(names, key=len, reverse=True)
        if len(name) > 2 and name.encode("utf-8") != NEUTRAL)
    return re.compile(rb"(?:" + alternatives + rb")(?:\.[A-Za-z0-9-]+)*",
                      re.IGNORECASE)


def make_materials_scene(folder: str) -> None:
    """The scene test_renders loads: two Karma materials under `/mat`, so an assertion that the load brought materials with it has something to find."""
    scratch = tempfile.mkdtemp(prefix="amaze_fixture_mat_")
    hou.hipFile.clear(suppress_save_prompt=True)
    neutral_scene_vars(scratch)   # AFTER the clear, which puts every global variable back to the session's own
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


def verify_no_identity(folder: str) -> int:
    """Refuse to leave a fixture carrying a home path, an account name or a machine name. Returns how many carried one. ▸r/author-stamp"""
    home = re.compile(rb"(?:/Users/|/home/|C:\\Users\\)[A-Za-z0-9_.-]+")
    stamped = re.compile(rb"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+\.[A-Za-z]{2,}")
    mine = identity_pattern()
    bad = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, folder)
            try:
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            for found in set(home.findall(blob)):
                text = found.decode("utf-8", "replace")
                if not text.endswith(("/someone", "/someone-else", "/projects")):
                    bad.append((rel, text))
            for found in set(stamped.findall(blob)) | set(mine.findall(blob)):
                if found != stand_in(found):
                    bad.append((rel, found.decode("utf-8", "replace")))
    for rel, text in sorted(set(bad)):
        print("  !! %s carries %s" % (rel, text))
    return len(set(bad))


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

    with open(os.path.join(OUT, "readme.txt"), "w") as handle:   # KIND_OTHER: recognised by nothing, must still list and draw an OS icon rather than being skipped
        handle.write("fixture\n")
    shutil.copy2(png, os.path.join(nested, "nested.png"))

    files = sorted(os.listdir(OUT))
    total = sum(os.path.getsize(os.path.join(OUT, f))
                for f in files if os.path.isfile(os.path.join(OUT, f)))
    print("\n%d entries, %.1f KB total" % (len(files), total / 1024.0))

    redacted = redact_tree(OUT) + redact_tree(SCENES)
    print("redacted %d stamped identit%s"
          % (redacted, "y" if redacted == 1 else "ies"))
    carried = verify_no_identity(OUT) + verify_no_identity(SCENES)
    if carried:
        print("REFUSED: %d fixture(s) still carry an account name, a "
              "machine name or a home directory - not publishable, fix "
              "the writer above" % carried)
        return 1
    print("verified: no fixture carries an identity or a home directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
