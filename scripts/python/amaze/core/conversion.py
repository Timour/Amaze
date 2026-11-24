"""A file on disk to a thumbnail-sized QImage, or a reason. ▸o/conversion ▸p/conversion-shape"""

import contextlib
import functools
import locale
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time

from PySide6 import QtCore, QtGui

from amaze.core import debug
from amaze.helpers import hostos


FIT = "fit"    # what the file needs, measured, never read off the extension ▸r/conversion-internals
FORMAT = "format"

REASON_NONE = ""                       # there is an image; the other reasons decide retry or missing ▸p/conversion-shape
REASON_CANCELLED = "cancelled"
REASON_TOO_LARGE = "too-large"
REASON_UNREADABLE = "unreadable"
REASON_STALLED = "stalled"    # a converter's child process survived being killed: reads of the file hang

MAX_RESCUE_MEGABYTES = 1024    # the largest image any converter may decode in full ▸r/conversion-internals

CONVERT_TIMEOUT_MS = 30000    # how long any one converter may run before it is killed
READ_PROBE_SECONDS = 2.0    # how long a raw read of the file may take before its reads count as stuck


class Conversion:
    """What :func:`convert_image` returns: truthy with an image, else `reason` is a REASON_*."""

    __slots__ = ("image", "via", "need", "reason", "attempts", "uniform", "unfinished")

    def __init__(self, image=None, via="", need="", reason=REASON_UNREADABLE,
                 attempts=(), uniform=False, unfinished=False) -> None:
        self.image = image
        self.via = via
        self.need = need
        self.reason = REASON_NONE if image is not None else reason
        self.attempts = tuple(attempts)
        self.uniform = uniform    # returned although every pixel is identical ▸p/conversion-shape
        self.unfinished = image is None and unfinished    # no image, and a converter gave no verdict

    def __bool__(self) -> bool:
        return self.image is not None

    def __repr__(self) -> str:                                # pragma: no cover
        if self.image is not None:
            return "<Conversion %dx%d via %s>" % (
                self.image.width(), self.image.height(), self.via)
        return "<Conversion none: %s>" % (self.reason,)


def _decoded_megabytes(size: QtCore.QSize) -> float:
    """Bytes fully decoded at 4 a pixel; 0 when no size was declared. ▸r/conversion-internals"""
    if not size.isValid() or size.isEmpty():
        return 0.0
    return size.width() * size.height() * 4 / 1e6


_EXR_MAGIC = b"\x76\x2f\x31\x01"


def _exr_size(path: str) -> QtCore.QSize:
    """An OpenEXR file's data window, read from its own header; an invalid size for anything else."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(65536)
    except OSError:
        return QtCore.QSize()
    at = 8 if head[:4] == _EXR_MAGIC else len(head)    # past the magic and the version field
    while at < len(head) and head[at]:    # name NUL, type NUL, int32 size, value; a NUL ends them
        name_end = head.find(b"\0", at)
        type_end = head.find(b"\0", name_end + 1) if name_end > 0 else -1
        if type_end < 0 or type_end + 5 > len(head):
            break
        size = struct.unpack_from("<i", head, type_end + 1)[0]
        value = type_end + 5
        if (head[at:name_end] == b"dataWindow" and head[name_end + 1:type_end] == b"box2i"
                and size == 16 and value + 16 <= len(head)):
            x_min, y_min, x_max, y_max = struct.unpack_from("<4i", head, value)
            return QtCore.QSize(x_max - x_min + 1, y_max - y_min + 1)
        if size < 0:
            break
        at = value + size
    return QtCore.QSize()


_SIPS_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", _EXR_MAGIC, b"II*\x00", b"MM\x00*",
               b"#?RADIANCE", b"#?RGBE", b"8BPS", b"BM")
_TGA_FOOTER = b"TRUEVISION-XFILE.\x00"    # the last 18 bytes of a TGA 2.0 file


def _sips_reads(path: str) -> bool:
    """Is this file, by its HEADER, a format sips was measured to read? ▸r/conversion-internals"""
    try:
        with open(path, "rb") as handle:
            head = handle.read(18)
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - len(_TGA_FOOTER)))
            tail = handle.read()
    except OSError:
        return False
    if head.startswith(_SIPS_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return True
    if tail == _TGA_FOOTER:
        return True
    return _tga_v1(head)


def _tga_v1(head: bytes) -> bool:
    """A footerless TGA 1.0 has no magic: its header fields must all hold a TGA's values."""
    if len(head) < 18:
        return False
    width, height = struct.unpack_from("<HH", head, 12)
    return (head[1] in (0, 1) and head[2] in (1, 2, 3, 9, 10, 11)
            and head[16] in (8, 15, 16, 24, 32) and width > 0 and height > 0)


def _reads_promptly(path: str, seconds: float = READ_PROBE_SECONDS) -> bool:
    """Does a raw read of the file's two ends return within `seconds`? ▸p/conversion-shape"""
    done = threading.Event()

    def _read():
        try:
            with open(path, "rb") as handle:
                handle.read(65536)
                handle.seek(max(0, handle.seek(0, os.SEEK_END) - 65536))
                handle.read()
        except OSError:
            pass    # an error came back, so the reads are not stuck
        done.set()

    threading.Thread(target=_read, name="amaze-read-probe", daemon=True).start()    # a hung read blocks only this thread
    return done.wait(seconds)


@contextlib.contextmanager
def _scratch_png():
    """THE temp file creation and removal, for every adapter that needs one. ▸p/conversion-shape"""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            try:    # a temp file that cannot be removed never changes the result ▸p/conversion-shape
                os.remove(path)
            except OSError:
                debug.event("convert", "temp png cleanup skipped", path=path)


CANCELLED = "cancelled"    # what `_run_process` answers besides a converter's own error text
TIMED_OUT = "timed out"
ABANDONED = "timed out, and its child outlived the kill - the file's reads are stuck"
FAILED_TO_START = "failed to start"
UNFINISHED = (TIMED_OUT, ABANDONED, FAILED_TO_START)    # the converter gave no verdict on the file

POLL_SECONDS = 0.1    # how often a running converter's exit and the cancel callback are read
KILL_GRACE_SECONDS = 0.5    # how long a killed converter may take to exit before it is abandoned

_ABANDONED: list = []    # killed converters still running after the grace; `_collect_abandoned` drops them
_ABANDONED_GUARD = threading.Lock()    # converters run on several worker threads


def _spawn(program: str, args: list, errors, output=subprocess.DEVNULL):
    """Start a converter with its stderr in `errors`; posix_spawn on macOS. ▸r/qprocess-sigchld"""
    live = QtCore.QProcessEnvironment.systemEnvironment()    # os.environ misses what Houdini set later
    return subprocess.Popen(
        [program] + list(args), stdin=subprocess.DEVNULL, stdout=output,
        stderr=errors, env={key: live.value(key) for key in live.keys()},
        close_fds=not hostos.is_macos(),    # False is what makes Python use posix_spawn there
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))    # Windows: no console


def _run_process(program: str, args: list, timeout_ms: int = CONVERT_TIMEOUT_MS,
                 cancelled=None, output=subprocess.DEVNULL) -> tuple:
    """(True, "") or (False, why): CANCELLED, one of UNFINISHED, or `exit N: <stderr>`."""
    _collect_abandoned()
    with tempfile.TemporaryFile() as errors:    # a file, so a converter that writes much never blocks on a pipe
        try:
            process = _spawn(program, args, errors, output)
        except OSError as exc:
            debug.event("convert", "a converter did not start", program=program, error=str(exc))
            return False, FAILED_TO_START
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            try:
                code = process.wait(POLL_SECONDS)    # asks the system about this one child
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled is not None and cancelled():
                _stop(process)
                return False, CANCELLED
            if time.monotonic() >= deadline:
                debug.event("convert", "a converter hit its timeout",    # the FULL path ▸r/conversion-internals
                            program=program, args=args, timeout_ms=timeout_ms)
                return False, TIMED_OUT if _stop(process) else ABANDONED
        if code == 0:
            return True, ""
        errors.seek(0)
        stderr = text_of(errors.read()).strip()
    return False, f"exit {code}: {stderr}"


def text_of(raw: bytes) -> str:
    """A Houdini tool's output as text: the ANSI codepage on Windows ▸r/conversion-internals"""
    try:
        return raw.decode(locale.getpreferredencoding(False))
    except (UnicodeDecodeError, LookupError):
        return raw.decode("utf-8", "replace")


def _stop(process) -> bool:
    """Kill a converter; True once it has exited, False when it is kept in `_ABANDONED`."""
    if _gone_after_kill(process):
        return True
    with _ABANDONED_GUARD:
        _ABANDONED.append(process)
    debug.event("convert", "helper kept in _ABANDONED until it exits",
                program=process.args[0], args=list(process.args[1:]))
    return False


def _gone_after_kill(process) -> bool:
    """Kill, then wait KILL_GRACE_SECONDS for the exit; a child in a stuck read outlives it."""
    try:
        process.kill()
        process.wait(KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        pass    # it had exited already
    return True


def _collect_abandoned() -> None:
    """Drop from `_ABANDONED` every converter that has exited since it was put there."""
    with _ABANDONED_GUARD:
        _ABANDONED[:] = [process for process in _ABANDONED if process.poll() is None]


@functools.cache
def _have_pillow() -> bool:
    """Is Pillow importable in this Houdini's Python? Cached. ▸r/conversion-internals"""
    try:
        import PIL.Image                                      # noqa: F401
    except Exception:                                         # noqa: BLE001
        return False
    return True




def _produce_sips(source: str, out_path: str, ctx, resample: bool) -> tuple:
    """macOS's `/usr/bin/sips`, registered for both FIT and FORMAT. ▸r/sips-hdr ▸r/conversion-internals"""
    if not hostos.is_macos():
        return False, "not macOS"
    if not _sips_reads(source):
        return False, "not a format sips is measured to read"
    sips = shutil.which("sips")
    if sips is None:
        return False, "sips not on PATH"
    args = []
    if resample:
        args += ["-Z", str(max(1, int(ctx.size)))]
    args += ["-s", "format", "png", source, "--out", out_path]
    ok, err = _run_process(sips, args, cancelled=ctx.cancelled)
    return (True, "") if ok else (False, err)


def _produce_iconvert(source: str, out_path: str, ctx) -> tuple:
    """Houdini's own converter, `.rat` included; FORMAT only, it cannot resize. ▸r/conversion-internals"""
    iconvert = hostos.bundled_binary(ctx.hfs, "iconvert")
    if iconvert is None:
        return False, "iconvert not in $HFS/bin"
    ok, err = _run_process(iconvert, [source, out_path], cancelled=ctx.cancelled)
    return (True, "") if ok else (False, err)


def _produce_icp(source: str, out_path: str, ctx) -> tuple:
    """Houdini's own resampler, scaling by the size Qt declared; FIT only. ▸r/conversion-internals"""
    declared = ctx.declared.get(source)
    if declared is None or not declared.isValid() or declared.isEmpty():
        return False, "no declared size to scale from"
    icp = hostos.bundled_binary(ctx.hfs, "icp")
    if icp is None:
        return False, "icp not in $HFS/bin"
    percent = 100.0 * ctx.size / max(declared.width(), declared.height())    # `-s` keeps the aspect; `-w` alone is ignored
    ok, err = _run_process(icp, ["-s", "%.4f" % percent, source, out_path],
                           cancelled=ctx.cancelled)
    return (True, "") if ok else (False, err)


_PILLOW_GUARD = threading.Lock()    # the decompression-bomb limit is process-global; converters use threads


def _open_unguarded(source: str):
    """`Image.open` with Pillow's pixel limit lifted for this open only. ▸r/conversion-internals"""
    from PIL import Image

    with _PILLOW_GUARD:
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None    # the file came from the user's own library
        try:
            return Image.open(source)    # open and crop check the limit; this path never crops
        finally:
            Image.MAX_IMAGE_PIXELS = previous


def _produce_pillow(source: str, out_path: str, ctx) -> tuple:
    """Resample with Houdini's own Pillow: `reduce()`, then resize. ▸r/conversion-internals"""
    if not _have_pillow():
        return False, "no Pillow in this Houdini's Python"
    try:
        from PIL import Image

        with _open_unguarded(source) as opened:
            factor = max(1, min(opened.width // max(ctx.size, 1),
                                opened.height // max(ctx.size, 1)))
            image = opened.reduce(factor) if factor > 1 else opened.copy()

        if ctx.cancelled():
            return False, "cancelled"
        resample = getattr(Image, "Resampling", Image).BILINEAR    # both `Image.Resampling` spellings, for H21 and H22 ▸r/conversion-internals
        image.thumbnail((ctx.size, ctx.size), resample)
        image.convert("RGB").save(out_path, "PNG")
    except Exception as exc:                                  # noqa: BLE001
        return False, str(exc)
    return True, ""


_SIPS_FIT = functools.partial(_produce_sips, resample=True)
_SIPS_FORMAT = functools.partial(_produce_sips, resample=False)


_FIT_ADAPTERS = (    # resamplers only, sips first; sips only for headers it can read ▸r/conversion-internals
    ("sips (resampling)", _SIPS_FIT),
    ("pillow", _produce_pillow),
    ("icp (resampling)", _produce_icp),
)

_FORMAT_ADAPTERS = (    # Pillow first: it fails fastest on a file it cannot read ▸r/conversion-internals
    ("pillow", _produce_pillow),
    ("sips (format only)", _SIPS_FORMAT),
    ("iconvert", _produce_iconvert),
)



class _Ctx:
    """One conversion's working state: the target size, the cancel callback, and the attempts."""

    def __init__(self, path, size, cancelled, hfs) -> None:
        self.path = path
        self.size = max(1, int(size))
        self._cancelled = cancelled
        self.hfs = hfs if hfs is not None else os.environ.get("HFS", "")
        self.attempts = []
        self.unfinished = False    # a converter was cancelled, timed out or did not start
        self.need = ""    # what this file turned out to need; the first value set is kept ▸r/conversion-internals
        self.fallback = None    # a uniform image kept in case nothing does better ▸p/conversion-shape
        self.fallback_via = ""
        self.declared = {}    # path -> the size Qt declared for it, which icp scales from

    def needs(self, need: str) -> None:
        if not self.need:
            self.need = need

    def cancelled(self) -> bool:
        return self._cancelled is not None and self._cancelled()

    WHY_LIMIT = 160    # characters of converter stderr kept per attempt ▸p/conversion-shape

    def tried(self, name: str, why: str) -> None:
        why = " ".join((why or "").split())
        if len(why) > self.WHY_LIMIT:
            why = why[:self.WHY_LIMIT - 1] + "…"
        self.attempts.append((name, why))

    def trail(self) -> str:
        return "; ".join("%s: %s" % (n, w or "no answer")
                         for n, w in self.attempts)


class _Step:
    """What one read attempt came back with: an image, or the NEED that stopped it plus a reason."""

    __slots__ = ("image", "via", "need", "reason", "uniform")

    def __init__(self, image=None, via="", need="", reason=REASON_UNREADABLE,
                 uniform=False) -> None:
        self.image = image
        self.via = via
        self.need = need
        self.reason = reason
        self.uniform = uniform


def _fit_to_contract(image: QtGui.QImage, size: int) -> QtGui.QImage:
    """Scale down to fit `size`; called from `_read_qt` and nowhere else. ▸p/conversion-shape"""
    if image.width() <= size and image.height() <= size:
        return image
    return image.scaled(
        size, size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


def _uniform(image: QtGui.QImage) -> bool:
    """Is every pixel identical, exactly, on an 8x8 smooth downsample? ▸r/conversion-internals"""
    if image.isNull() or image.width() == 0 or image.height() == 0:
        return True
    small = image.scaled(
        8, 8,
        QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    first = small.pixel(0, 0)
    for y in range(small.height()):
        for x in range(small.width()):
            if small.pixel(x, y) != first:
                return False
    return True


def _rejection_reason(image: QtGui.QImage) -> str:
    """Is an adapter's output acceptable? Empty when it is, else why not. ▸p/conversion-shape"""
    if image is None or image.isNull():
        return "null image"
    if image.width() <= 0 or image.height() <= 0:
        return "empty image"
    if _uniform(image):
        return "every pixel identical - no picture in it"
    return ""


def _read_qt(path: str, size: int) -> tuple:
    """Decode in process, scaled: (image or None, declared size, error). ▸r/conversion-internals"""
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)          # honour EXIF orientation
    declared = reader.size()
    if declared.isValid() and not declared.isEmpty():
        target = declared.scaled(
            size, size, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        if not target.isEmpty():
            reader.setScaledSize(target)
        image = reader.read()
        if not image.isNull():
            return _fit_to_contract(image, size), declared, ""
    whole = QtGui.QImage(path)    # no declared size: a whole read, full size ▸r/conversion-internals
    if not whole.isNull():
        return _fit_to_contract(whole, size), declared, ""
    return None, declared, reader.errorString()


def _run_adapters(adapters, source: str, ctx: _Ctx, need: str,
                  reread) -> _Step:
    """Try each adapter, check it via `reread`, stop at the first good one. ▸r/conversion-internals"""
    for name, produce in adapters:
        if ctx.cancelled():
            return _Step(need=need, reason=REASON_CANCELLED)
        with _scratch_png() as out_path:
            wrote, why = produce(source, out_path, ctx)
            if not wrote:
                if why == CANCELLED:
                    ctx.tried(name, why)
                    return _Step(need=need, reason=REASON_CANCELLED)
                ctx.tried(name, why)
                if why in UNFINISHED:
                    ctx.unfinished = True
                if why == ABANDONED:    # the FILE is tested: if its reads hang, no second converter runs
                    if not _reads_promptly(source):
                        return _Step(need=need, reason=REASON_STALLED)
                    debug.event("convert", "a converter was abandoned on a file that reads - the next one runs",
                                path=source, converter=name)
                continue
            step = reread(out_path, ctx)
            if step.image is None:
                ctx.tried(name, "output unreadable: %s" % (step.reason,))
                continue
            rejected = _rejection_reason(step.image)
            if rejected:
                ctx.tried(name, rejected)
                if ctx.fallback is None:
                    ctx.fallback = step.image    # kept, not returned ▸p/conversion-shape
                    ctx.fallback_via = name
                continue
            via = name    # names both adapters when the reread used a converter too ▸r/conversion-internals
            if step.via and step.via != "qt":
                via = "%s -> %s" % (name, step.via)
            return _Step(image=step.image, via=via)
    return _Step(need=need, reason=REASON_UNREADABLE)


def _fitted(path: str, ctx: _Ctx) -> _Step:
    """Read `path` at the target size, resampling if Qt cannot. ▸r/conversion-internals"""
    image, declared, error = _read_qt(path, ctx.size)
    if image is not None:
        return _Step(image=image, via="qt")

    declared_mb = _decoded_megabytes(declared)
    if declared_mb <= QtGui.QImageReader.allocationLimit():
        ctx.tried("qt", error or "Qt could not read this file at all")    # a null read means an unsupported format or a damaged file ▸p/conversion-shape
        ctx.needs(FORMAT)
        return _Step(need=FORMAT, reason=REASON_UNREADABLE)

    ctx.tried("qt", "decode would pass Qt's allocation limit")
    ctx.needs(FIT)
    ctx.declared[path] = declared
    if declared_mb > MAX_RESCUE_MEGABYTES:
        debug.event(    # declined, and logged ▸p/conversion-shape
            "convert", "image too large to convert - declined",
            path=path, declared_mb=round(declared_mb),
            ceiling_mb=MAX_RESCUE_MEGABYTES,
            why="decode would pass Qt's allocation limit",
            note="a conversion decodes the whole image before shrinking "
                 "it; past the ceiling that risks the session")
        return _Step(need=FIT, reason=REASON_TOO_LARGE)

    def _reread(produced, inner_ctx):
        # a resampler's output is read by Qt only, with no second converter
        img, _declared, err = _read_qt(produced, inner_ctx.size)
        return _Step(image=img, reason=err or REASON_UNREADABLE)

    return _run_adapters(_FIT_ADAPTERS, path, ctx, FIT, _reread)


def convert_image(path: str, size: int, cancelled=None, hfs=None) -> Conversion:
    """A file on disk to a thumbnail-sized `Conversion`; polls `cancelled`. ▸p/conversion-shape"""
    ctx = _Ctx(path, size, cancelled, hfs)

    step = _fitted(path, ctx)
    if step.image is not None:
        return _converted(ctx, step)
    if step.need != FORMAT:
        return _not_converted(ctx, step.need, step.reason)    # FIT already tried every converter inside _fitted

    declared_mb = _decoded_megabytes(_exr_size(path))    # Qt declares no size for an EXR; its header does
    if declared_mb > MAX_RESCUE_MEGABYTES:
        debug.event("convert", "image too large to convert - declined",
                    path=path, declared_mb=round(declared_mb),
                    ceiling_mb=MAX_RESCUE_MEGABYTES, why="the EXR header's data window")
        return _not_converted(ctx, FORMAT, REASON_TOO_LARGE)
    step = _run_adapters(_FORMAT_ADAPTERS, path, ctx, FORMAT, _fitted)
    if step.image is not None:
        return _converted(ctx, step)
    return _not_converted(ctx, FORMAT, step.reason)


def _converted(ctx: _Ctx, step: _Step) -> Conversion:
    """Log which converter succeeded and why the first try failed, if any. ▸p/conversion-shape"""
    if ctx.attempts:
        debug.event("convert", "converted by a fallback",
                    path=ctx.path, via=step.via, need=ctx.need,
                    why=ctx.attempts[0][1], tried=ctx.trail())
    return Conversion(image=step.image, via=step.via, need=ctx.need,
                      attempts=ctx.attempts)


def _not_converted(ctx: _Ctx, need: str, reason: str) -> Conversion:
    """No adapter produced a picture; a kept uniform image is returned here. ▸p/conversion-shape"""
    if reason in (REASON_UNREADABLE, REASON_STALLED) and ctx.fallback is not None:
        debug.event("convert", "converted, but every pixel is identical",
                    path=ctx.path, via=ctx.fallback_via, need=need,
                    tried=ctx.trail(),
                    note="delivered because no converter did better - the "
                         "file itself is one flat colour")
        return Conversion(image=ctx.fallback,
                          via=ctx.fallback_via, need=need,
                          attempts=ctx.attempts, uniform=True)
    if reason == REASON_CANCELLED:
        return Conversion(need=need, reason=reason, attempts=ctx.attempts,    # browsing away is not a failure and is not logged ▸p/conversion-shape
                          unfinished=True)
    if reason != REASON_TOO_LARGE:
        said = ("no thumbnail - a converter stalled on its reads" if reason == REASON_STALLED
                else "no thumbnail - nothing could read it")
        debug.event("convert", said,    # TOO_LARGE was already logged, with its limit
                    path=ctx.path, need=need,
                    why=ctx.attempts[0][1] if ctx.attempts else "",
                    tried=ctx.trail(),
                    limit_mb=QtGui.QImageReader.allocationLimit(),
                    macos=hostos.is_macos(), pillow=_have_pillow())
    return Conversion(need=need, reason=reason, attempts=ctx.attempts,
                      unfinished=ctx.unfinished or reason == REASON_STALLED)
