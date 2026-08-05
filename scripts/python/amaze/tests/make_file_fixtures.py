"""Build the File-section fixture folder: one tiny file per KIND.

    hython make_file_fixtures.py

Run it when the fixture set needs to change; the output is COMMITTED,
so the suite never generates anything at test time.

WHY GENERATED, NOT COPIED. The File section's locations on a real
machine are the user's own photograph and texture archives, and a
fixture must never be a copy of those - `tests/assets/` is tracked and
publishes to the public repo. Every file here is drawn from a formula
in this script: a 32x32 colour ramp, a two-primitive box, an empty
scene. Nothing depicts anything.

Every image format goes through Houdini's own `iconvert`, which is the
same decoder chain the Thumbnail Engine's CONVERT provider uses - so
these exercise the real route, including the two formats that have
their own probed branches (`.exr` and `.rat`, research.md ▸ Houdini
image writing).
"""
import os
import shutil
import subprocess
import sys

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "files")

#: Every image format the File section recognises, written from one
#: source PNG so a decode difference is the only thing that can differ.
IMAGE_FORMATS = ("jpg", "tif", "tga", "bmp", "exr", "hdr", "rat")

#: Names that have broken extension matching before. Contents do not
#: matter; the NAME is the fixture.
EDGE_NAMES = (
    "UPPERCASE EXTENSION.PNG",     # matching is case-insensitive
    "with spaces.png",             # quoting in every path that joins it
    "wíth-únicøde.png",            # non-ASCII, NFD/NFC on macOS
)


def iconvert(src: str, dest: str) -> bool:
    tool = os.path.join(hou.getenv("HFS") or "", "bin", "iconvert")
    try:
        subprocess.run([tool, src, dest], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        print("  !! %s failed: %s" % (os.path.basename(dest), exc))
        return False
    return os.path.exists(dest)


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


def make_scenes(folder: str) -> None:
    """All three scene extensions - each is its own KIND_HIP label
    ('Hiplc', not 'HIPLC'), and matched_extension picks the longest."""
    for name in ("empty.hip", "empty.hiplc", "empty.hipnc"):
        try:
            hou.hipFile.save(os.path.join(folder, name),
                             save_to_recent_files=False)
        except hou.Error as exc:
            print("  !! %s failed: %s" % (name, exc))


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

    # KIND_OTHER: recognised by nothing, must still list and draw an
    # OS icon rather than being skipped.
    with open(os.path.join(OUT, "readme.txt"), "w") as handle:
        handle.write("fixture\n")
    shutil.copy2(png, os.path.join(nested, "nested.png"))

    files = sorted(os.listdir(OUT))
    total = sum(os.path.getsize(os.path.join(OUT, f))
                for f in files if os.path.isfile(os.path.join(OUT, f)))
    print("\n%d entries, %.1f KB total" % (len(files), total / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
