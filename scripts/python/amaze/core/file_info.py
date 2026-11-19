"""What the info pane shows: a selection's rows, and a file's facts from its header or a tool."""

from __future__ import annotations

import dataclasses
import functools
import locale
import os
import re
import subprocess
import tempfile
import threading
import time

from PySide6 import QtCore

from amaze.core import debug, geo_library, scene_files, workers
from amaze.helpers import hostos

KIND_IMAGE = "image"
KIND_GEOMETRY = "geometry"
KIND_USD = "usd"
KIND_ALEMBIC = "alembic"
KIND_TEXTURES = "textures"
KIND_SIZES = "sizes"

IMAGE_ENDINGS = (".exr", ".hdr", ".jpg", ".jpeg", ".png", ".pic", ".rat",    # each read measured;
                 ".tif", ".tiff", ".tga", ".bmp", ".gif", ".tx")    # another ending: file rows only
GEOMETRY_ENDINGS = (".bgeo.sc", ".bgeo.gz", ".bgeo", ".geo", ".obj")
USD_ENDINGS = (".usd", ".usda", ".usdc", ".usdz")
ALEMBIC_ENDINGS = ()

_KNOWN_ENDINGS = (geo_library.GEO_EXTENSIONS + geo_library.CACHE_EXTENSIONS    # the two-part ones
                  + scene_files.HIP_EXTENSIONS)


@dataclasses.dataclass(frozen=True)
class Request:
    """One background read. `kind`: "image", "geometry", "usd", "alembic", "textures" or "sizes"."""

    kind: str
    paths: tuple


@dataclasses.dataclass(frozen=True)
class Subject:
    """What the pane shows for a selection: the header, the rows known at once, one optional read."""

    key: str    # identifies the selection; an answer that arrives for another key is dropped
    name: str
    type: str
    before: tuple = ()    # (label, value) rows shown at once, above the rows the read adds
    after: tuple = ()    # rows shown at once, below them
    request: Request | None = None


def size_text(byte_count: int) -> str:
    """A size as the pane writes it: "512 B", "840 KB", "12.4 MB", "1.3 GB"."""
    count = max(int(byte_count), 0)
    if count < 1024:
        return "%d B" % count
    if count < 1024 * 1024:
        return "%d KB" % round(count / 1024)
    if count < 1024 ** 3:
        return "%.1f MB" % (count / 1024 ** 2)
    return "%.1f GB" % (count / 1024 ** 3)


def date_text(timestamp: float) -> str:
    """A time as the pane writes it, local time: "2021-08-10"."""
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def _ending(path: str) -> str:
    """The file's ending, lower case with its dot: the longest known one, else the last suffix."""
    name = os.path.basename(path)
    return hostos.matched_extension(name, _KNOWN_ENDINGS) or os.path.splitext(name)[1].lower()


def format_text(path: str) -> str:
    """The file's format from its ending, upper case: "EXR", "BGEO.SC", "HIPLC"; "" for none."""
    return _ending(path)[1:].upper()


def file_rows(path: str) -> tuple:
    """(before, after) for a file, from one `os.stat`: Name, Created, Modified, Size, Format; Folder."""
    name = os.path.basename(path)
    ending = _ending(path)
    before = [("Name", name[:len(name) - len(ending)] if ending else name)]
    try:
        info = os.stat(path)
    except OSError:
        info = None
    if info is not None:
        created = getattr(info, "st_birthtime", None)    # macOS and Windows keep one; Linux does not
        if created:
            before.append(("Created", date_text(created)))
        before.append(("Modified", date_text(info.st_mtime)))
        before.append(("Size", size_text(info.st_size)))
    if ending:
        before.append(("Format", format_text(path)))
    return tuple(before), (("Folder", os.path.dirname(path)),)


def request_for_file(path: str) -> Request | None:
    """The read that adds a file's own rows, or None for a format that has none."""
    name = os.path.basename(path)
    for kind, endings in ((KIND_IMAGE, IMAGE_ENDINGS), (KIND_GEOMETRY, GEOMETRY_ENDINGS),
                          (KIND_USD, USD_ENDINGS), (KIND_ALEMBIC, ALEMBIC_ENDINGS)):
        if endings and hostos.has_extension(name, endings):
            return Request(kind, (path,))
    return None


def request_for_textures(paths) -> Request | None:
    """The read that finds the largest of a material's texture files, or None for no files."""
    found = tuple(path for path in paths if path)
    return Request(KIND_TEXTURES, found) if found else None


def request_for_sizes(paths) -> Request | None:
    """The read that adds up the sizes of several items' files, or None for no files."""
    found = tuple(path for path in paths if path)
    return Request(KIND_SIZES, found) if found else None


TOOL_TIMEOUT_SECONDS = 10.0    # how long one call of a Houdini tool may run before it is killed
POLL_SECONDS = 0.1    # how often a running tool's exit and the cancel callback are read
KILL_GRACE_SECONDS = 0.5    # how long a killed tool may take to exit before it is left running
PATHS_PER_CALL = 100    # the most files one `iinfo` call is given
SIZE_CHECK_EVERY = 100    # files added up between two reads of the cancel callback
PRIM_CHECK_EVERY = 1000    # prims counted between two reads of the cancel callback

_LEFT: list = []    # killed tools still running after the grace; dropped once they exit
_LEFT_GUARD = threading.Lock()    # tools run on several worker threads


def run_tool(program: str, args: list, cancelled) -> str | None:
    """The tool's stdout at any exit code; None if it did not start, timed out or was cancelled."""
    with _LEFT_GUARD:
        _LEFT[:] = [process for process in _LEFT if process.poll() is None]
    live = QtCore.QProcessEnvironment.systemEnvironment()    # os.environ misses what Houdini set later
    with tempfile.TemporaryFile() as output:    # a file, so a tool that writes much never blocks
        try:
            process = subprocess.Popen(    # posix_spawn on macOS, as conversion._spawn ▸r/qprocess-sigchld
                [program] + list(args), stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.DEVNULL, env={key: live.value(key) for key in live.keys()},
                close_fds=not hostos.is_macos(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))    # Windows: no console
        except OSError as exc:
            debug.event("info", "a tool did not start", program=program, error=str(exc))
            return None
        deadline = time.monotonic() + TOOL_TIMEOUT_SECONDS
        while True:
            try:
                process.wait(POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled():
                _stop(process)
                return None
            if time.monotonic() >= deadline:
                debug.event("info", "a tool hit its timeout", program=program, args=list(args))
                _stop(process)
                return None
        output.seek(0)
        raw = output.read()
    try:    # Houdini's tools write the ANSI codepage on Windows ▸r/conversion-internals
        return raw.decode(locale.getpreferredencoding(False))
    except (UnicodeDecodeError, LookupError):
        return raw.decode("utf-8", "replace")


def _stop(process) -> None:
    """Kill a tool and wait KILL_GRACE_SECONDS for its exit; one still running goes in `_LEFT`."""
    try:
        process.kill()
        process.wait(KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        with _LEFT_GUARD:
            _LEFT.append(process)
    except OSError:
        pass    # it had exited already


def _lines(text: str):
    """(key, value) for every `key: value` line, stripped, in order."""
    for line in text.splitlines():
        key, colon, value = line.strip().partition(":")
        if colon:
            yield key.strip(), value.strip()


def _resolution(value: str):
    """(width, height) from "2048 x 2048", or None."""
    match = re.match(r"(\d+)\s*x\s*(\d+)", value)
    return (int(match.group(1)), int(match.group(2))) if match else None


_COLOR_SPACES = {"linear": "Linear", "srgb": "sRGB"}


def parse_image(text: str) -> list:
    """The rows of one file's plain `iinfo` output; the first plane's values when it has several."""
    found = {}
    for key, value in _lines(text):
        if key not in found:    # the first plane comes first
            found[key] = value
    rows = []
    size = _resolution(found.get("Resolution", ""))
    if size:
        rows.append(("Dimensions", "%d x %d" % size))
    if found.get("Color Space"):
        rows.append(("Color Space", _COLOR_SPACES.get(found["Color Space"], found["Color Space"])))
    if found.get("Data"):
        rows.append(("Bit Depth", found["Data"]))
    if found.get("Color Model"):
        rows.append(("Channels", found["Color Model"]))
    if found.get("Compression"):
        rows.append(("Compression", found["Compression"].split()[0].rstrip(",")))
    if found.get("MipMaps") in ("true", "false"):
        rows.append(("MIP Maps", "Yes" if found["MipMaps"] == "true" else "No"))
    elif "MIP Resolutions" in found:
        rows.append(("MIP Maps", "Yes"))
    return rows


def parse_sizes(text: str) -> list:
    """(width, height) of every file in several files' `iinfo` output."""
    sizes = [_resolution(value) for key, value in _lines(text) if key == "Resolution"]
    return [size for size in sizes if size]


def largest_row(sizes) -> list:
    """The `Largest Texture` row for (width, height) pairs, by pixel count; [] for none."""
    if not sizes:
        return []
    return [("Largest Texture", "%d x %d" % max(sizes, key=lambda size: size[0] * size[1]))]


def parse_largest(text: str) -> list:
    """The `Largest Texture` row of several files' `iinfo` output; [] for none."""
    return largest_row(parse_sizes(text))


MIP_LEVEL_LIMIT = 64    # the most MIP levels counted in one picture
_FLOAT_FORMATS = ("half", "float", "double")    # OpenImageIO's names for its float pixel types


def open_header(path: str):
    """The picture opened by OpenImageIO, which reads its header only; None when it has no reader."""
    try:
        import OpenImageIO
    except ImportError:
        return None
    source = OpenImageIO.ImageInput.open(path)
    if source is None:
        OpenImageIO.geterror()    # the reason is kept until it is read
    return source


def header_rows(source) -> list:
    """The rows of a picture `open_header` returned, its first part's values; does not close it."""
    spec = source.spec()
    rows = [("Dimensions", "%d x %d" % (spec.width, spec.height))]
    space = spec.get_string_attribute("oiio:ColorSpace")
    if space:
        rows.append(("Color Space", _COLOR_SPACES.get(space, space)))
    bits = spec.get_int_attribute("oiio:BitsPerSample") or spec.format.size() * 8
    kind = "float" if str(spec.format) in _FLOAT_FORMATS else "integer"
    rows.append(("Bit Depth", "%d bit %s" % (bits, kind)))
    names = list(spec.channelnames)
    if names:    # "RGBA" for one-letter names, "R, G, B, depth.Z" otherwise
        rows.append(("Channels", ("" if all(len(name) == 1 for name in names) else ", ").join(names)))
    compression = spec.get_string_attribute("compression")
    if compression:
        rows.append(("Compression", "None" if compression == "none" else compression.upper()))
    levels = 0
    while levels < MIP_LEVEL_LIMIT and source.seek_subimage(0, levels):
        levels += 1
    if levels > 1 or source.format_name() == "openexr":    # an EXR says No; other formats say nothing
        rows.append(("MIP Maps", "Yes" if levels > 1 else "No"))
    return rows


def header_size(path: str):
    """(width, height) from the picture's header; None when OpenImageIO has no reader for it."""
    source = open_header(path)
    if source is None:
        return None
    try:
        spec = source.spec()
        return spec.width, spec.height
    finally:
        source.close()


_COUNT = re.compile(r"^([\d,]+) (Points|Vertices|Primitives)$")
_TYPE = re.compile(r"^([\d,]+) (\S.*)$")
_ATTRIBUTES = re.compile(r"^\d+ (point|vertex|primitive|global) attributes:\s*(.*)$")
_ATTRIBUTE_ORDER = ("point", "vertex", "primitive", "global")


def parse_geometry(text: str) -> list:
    """The rows of `ginfo -S` output."""
    counts, types, attributes = {}, [], {}
    size = software = None
    in_types = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("_"):    # the separator line ends the primitive types
            in_types = False
            continue
        count = _COUNT.match(line)
        if count:
            counts[count.group(2)] = count.group(1)
            in_types = count.group(2) == "Primitives"
            continue
        if in_types and _TYPE.match(line):
            types.append(line)
            continue
        attribute = _ATTRIBUTES.match(line)
        if attribute:
            names = [name.strip() for name in attribute.group(2).split(",") if name.strip()]
            attributes.setdefault(attribute.group(1), []).extend(names)
        elif line.startswith("Size:"):
            size = line[len("Size:"):]
        elif line.startswith("software -"):
            software = line[len("software -"):].strip()
    rows = [(label, counts[label]) for label in ("Points", "Vertices") if label in counts]
    if "Primitives" in counts:
        if len(types) == 1:
            rows.append(("Primitives", types[0]))
        elif types:
            rows.append(("Primitives", "%s (%s)" % (counts["Primitives"], ", ".join(types))))
        else:
            rows.append(("Primitives", counts["Primitives"]))
    names = [name for kind in _ATTRIBUTE_ORDER for name in attributes.get(kind, ())]
    if names:
        rows.append(("Attributes", ", ".join(names)))
    if size:
        try:
            sides = [float(side) for side in size.split(",")]
        except ValueError:
            sides = []
        if len(sides) == 3:
            rows.append(("Dimensions", " x ".join("%g" % round(side, 2) for side in sides)))
    if software:
        rows.append(("Saved With", software))
    return rows


def _read_usd(path: str, cancelled) -> list:
    """The rows of a USD stage opened without its payloads; [] on any error or a cancel."""
    try:
        from pxr import Usd, UsdGeom

        stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
        if stage is None or cancelled():
            return []
        count = 0
        for _prim in stage.Traverse():
            count += 1
            if count % PRIM_CHECK_EVERY == 0 and cancelled():
                return []
        rows = [("Prims", "{:,}".format(count)), ("Layers", str(len(stage.GetUsedLayers())))]
        default = stage.GetDefaultPrim()
        if default:
            rows.append(("Default Prim", str(default.GetPath())))
        rows.append(("Up Axis", str(UsdGeom.GetStageUpAxis(stage))))
        rows.append(("Meters Per Unit", "%g" % UsdGeom.GetStageMetersPerUnit(stage)))
        if stage.HasAuthoredTimeCodeRange():
            rows.append(("Frames", "%g - %g, %g fps" % (
                stage.GetStartTimeCode(), stage.GetEndTimeCode(), stage.GetTimeCodesPerSecond())))
        return rows
    except Exception as exc:                                  # noqa: BLE001 - a stage USD cannot open
        debug.event("info", "a USD stage could not be read", path=path, error=str(exc))
        return []


def _read_image(path: str, hfs: str, cancelled) -> list:
    """A picture's rows from its header; from `iinfo` when OpenImageIO has no reader for it."""
    source = open_header(path)
    if source is None:
        return _read_one("iinfo", [path], parse_image, hfs, cancelled)
    try:
        return header_rows(source)
    finally:
        source.close()


def _read_largest(paths, hfs: str, cancelled) -> list:
    """The `Largest Texture` row over every existing file: headers first, the rest by `iinfo`."""
    sizes, rest = [], []
    for path in paths:
        if cancelled():
            return []
        if os.path.isfile(path):
            size = header_size(path)
            if size:
                sizes.append(size)
            else:
                rest.append(path)
    iinfo = hostos.bundled_binary(hfs, "iinfo") if rest else None
    if iinfo is not None:
        for start in range(0, len(rest), PATHS_PER_CALL):
            text = run_tool(iinfo, rest[start:start + PATHS_PER_CALL], cancelled)
            if cancelled():
                return []
            sizes.extend(parse_sizes(text or ""))
    return largest_row(sizes)


def _read_sizes(paths, cancelled) -> list:
    """The `Size` row: the bytes of every existing file in `paths` added up."""
    total, seen = 0, False
    for number, path in enumerate(paths):
        if number % SIZE_CHECK_EVERY == 0 and cancelled():
            return []
        try:
            total += os.path.getsize(path)
            seen = True
        except OSError:
            pass    # a missing file adds nothing
    return [("Size", size_text(total))] if seen else []


def _read_one(program: str, args: list, parse, hfs: str, cancelled) -> list:
    """`parse` of one Houdini tool's output; [] when the tool is missing or gave no output."""
    tool = hostos.bundled_binary(hfs, program)
    if tool is None:
        return []
    text = run_tool(tool, args, cancelled)
    return parse(text) if text else []


def read(request: Request, hfs: str = "", cancelled=None) -> list:
    """The rows `request` adds; blocks, so it runs off the UI thread; [] when nothing could be read."""
    hfs = hfs or os.environ.get("HFS", "")
    cancelled = cancelled or (lambda: False)
    paths = list(request.paths)
    try:
        if request.kind == KIND_IMAGE and paths:
            rows = _read_image(paths[0], hfs, cancelled)
        elif request.kind == KIND_GEOMETRY and paths:
            rows = _read_one("ginfo", ["-S", paths[0]], parse_geometry, hfs, cancelled)
        elif request.kind == KIND_USD and paths:
            rows = _read_usd(paths[0], cancelled)
        elif request.kind == KIND_TEXTURES:
            rows = _read_largest(paths, hfs, cancelled)
        elif request.kind == KIND_SIZES:
            rows = _read_sizes(paths, cancelled)
        else:
            rows = []    # KIND_ALEMBIC: abcinfo prints no frame rate and no last frame
    except Exception as exc:                                  # noqa: BLE001 - the pane shows no rows
        debug.event("info", "a file read failed", kind=request.kind, error=str(exc))
        return []
    return [] if cancelled() else rows


class _ReadWorker(QtCore.QThread):
    """Runs one `read` off the UI thread and emits its rows unless it was cancelled."""

    answered = QtCore.Signal(int, str, object)    # (token, key, rows)

    def __init__(self, token: int, key: str, request: Request) -> None:
        super().__init__()
        self.token, self.key, self.request = token, key, request
        self._canceled = False    # the stop flag workers.stop() sets, the name every worker uses

    def cancel(self) -> None:
        self._canceled = True

    def _stopped(self) -> bool:
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        rows = read(self.request, cancelled=self._stopped)
        if not self._stopped():
            self.answered.emit(self.token, self.key, rows)


class _ReadEngine(QtCore.QObject):
    """Keeps every running read's thread until it ends; stops them on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, worker: _ReadWorker) -> None:
        """Start `worker` and keep it until its `finished` arrives on this thread."""
        worker.finished.connect(    # bound here, never sender(): ordering is per sender ▸r/model-contracts
            functools.partial(self._finished, worker))
        self._threads.append(worker)
        worker.start()

    def _finished(self, worker) -> None:
        self._threads = [t for t in self._threads if t is not worker and not workers.gone(t)]

    def shutdown(self) -> None:
        """Stop every read, THEN wait for each; safe twice and with nothing running."""
        workers.stop(self._threads, "info")
        self._threads = []


engine = workers.install(__name__, _ReadEngine, QtCore.QCoreApplication.instance())


class Reader(QtCore.QObject):
    """Runs one `read` at a time off the UI thread and emits its rows with the key they are for."""

    ready = QtCore.Signal(str, list)    # (key, rows), on the UI thread

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._token = 0    # the newest ask's number; an answer with another number is dropped
        self._worker = None

    def ask(self, key: str, request: Request) -> None:
        """Start the read for `key`; an answer still on its way for an earlier key is dropped."""
        self.stop()
        worker = _ReadWorker(self._token, key, request)
        worker.answered.connect(self._answered)    # queued: the worker emits on its own thread
        self.destroyed.connect(worker.cancel)    # a deleted Reader stops its read
        self._worker = worker
        engine.start(worker)

    def stop(self) -> None:
        """Drop every read on its way; nothing is emitted afterwards."""
        self._token += 1
        worker, self._worker = self._worker, None
        if worker is not None:
            try:
                worker.cancel()
                self.destroyed.disconnect(worker.cancel)
            except (RuntimeError, TypeError):
                pass    # its C++ side is gone, or it was never connected

    def _answered(self, token: int, key: str, rows) -> None:
        if token == self._token:
            self._worker = None
            self.ready.emit(key, list(rows))
