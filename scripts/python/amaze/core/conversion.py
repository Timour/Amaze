"""A file on disk to a thumbnail-sized QImage, or a reason. ▸o/conversion ▸p/conversion-shape"""

import contextlib
import functools
import locale
import os
import shutil
import struct
import tempfile
import threading

from PySide6 import QtCore, QtGui

from amaze.core import debug
from amaze.helpers import hostos


FIT = "fit"    # what the file needs, measured, never read off the extension ▸r/conversion-internals
FORMAT = "format"

REASON_NONE = ""                       # there is an image; the rest decide retry vs missing ▸p/conversion-shape
REASON_CANCELLED = "cancelled"
REASON_TOO_LARGE = "too-large"
REASON_UNREADABLE = "unreadable"
REASON_STALLED = "stalled"    # a converter's child outlived its kill: the file's reads are stuck

MAX_RESCUE_MEGABYTES = 1024    # the most any route may decode in full ▸r/conversion-internals

CONVERT_TIMEOUT_MS = 30000    # how long any one converter may run before it is killed


class Conversion:
    """What :func:`convert_image` answers: truthy with an image, else `reason` is a REASON_*."""

    __slots__ = ("image", "via", "need", "reason", "attempts", "uniform")

    def __init__(self, image=None, via="", need="", reason=REASON_UNREADABLE,
                 attempts=(), uniform=False) -> None:
        self.image = image
        self.via = via
        self.need = need
        self.reason = REASON_NONE if image is not None else reason
        self.attempts = tuple(attempts)
        self.uniform = uniform    # delivered although every pixel is identical ▸p/conversion-shape

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


@contextlib.contextmanager
def _scratch_png():
    """THE temp-file lifetime, for every adapter that needs one. ▸p/conversion-shape"""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            try:    # a held temp never masks the result ▸p/conversion-shape
                os.remove(path)
            except OSError:
                debug.event("convert", "temp png cleanup skipped", path=path)


class _Child(QtCore.QProcess):
    """A QProcess that can be told its exit was reaped elsewhere. ▸r/conversion-internals"""

    def mark_reaped_elsewhere(self):
        self.setProcessState(QtCore.QProcess.ProcessState.NotRunning)


ABANDONED = "timed out, and its child outlived the kill - the file's reads are stuck"


def _run_process(program: str, args: list, timeout_ms: int = CONVERT_TIMEOUT_MS,
                 cancelled=None) -> tuple:
    """(success, stderr_text) from `_wait_for`, or (False, ABANDONED) when its child was parked."""
    process = _Child()
    answer = _wait_for(process, program, args, timeout_ms, cancelled)
    if answer[1] != "cancelled" and process in _ABANDONED:
        return False, ABANDONED
    return answer


def _wait_for(process, program: str, args: list, timeout_ms: int,
              cancelled) -> tuple:
    """Run a subprocess to completion; returns (success, stderr_text). ▸r/conversion-internals"""
    loop = QtCore.QEventLoop()
    state = {"timed_out": False, "cancelled": False}

    def _quit():
        if loop.isRunning():
            loop.quit()

    process.finished.connect(_quit)
    process.errorOccurred.connect(_quit)

    timer = QtCore.QTimer()
    timer.setSingleShot(True)

    def _on_timeout():
        state["timed_out"] = True
        _quit()

    timer.timeout.connect(_on_timeout)

    def _check():    # the watchdog, always on: cancel and liveness ▸r/conversion-internals
        if cancelled is not None and cancelled():
            state["cancelled"] = True
            _quit()
            return
        pid = int(process.processId() or 0)
        if (pid and not hostos.is_windows()    # `os.kill(pid, 0)` kills on Windows ▸r/os-kill-windows
                and process.state() != QtCore.QProcess.ProcessState.NotRunning):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                state["vanished"] = True
                _quit()
            except OSError:
                pass          # alive but not ours to signal

    watchdog = QtCore.QTimer()
    watchdog.setInterval(100)
    watchdog.timeout.connect(_check)

    process.start(program, args)
    timer.start(timeout_ms)
    watchdog.start()
    try:
        loop.exec()
        timer.stop()
        watchdog.stop()
        if state.get("cancelled"):
            return (False, "cancelled")

        if state.get("vanished"):
            debug.event("convert", "a child's exit was reaped elsewhere",    # the child's work is the verdict; marked NotRunning ▸r/conversion-internals
                        program=program, waited_ms=timeout_ms)
            process.mark_reaped_elsewhere()
            return (True, "")

        if state["timed_out"]:
            already_gone = (process.state()    # Running is stuck; NotRunning exited without `finished` ▸p/conversion-shape
                            == QtCore.QProcess.ProcessState.NotRunning)
            debug.event("convert", "a converter hit its timeout",    # the FULL path, not a basename: a source scan bans name-reading calls here ▸r/conversion-internals
                        program=program,
                        args=args,
                        timeout_ms=timeout_ms,
                        child_already_exited=already_gone,
                        exit_code=(process.exitCode() if already_gone
                                   else None))
            return False, ("timed out (the child had already exited)"
                           if already_gone else "timed out")

        if process.error() == QtCore.QProcess.ProcessError.FailedToStart:
            return False, "failed to start"

        if (
            process.exitStatus() == QtCore.QProcess.ExitStatus.CrashExit
            and process.exitCode() == 0
        ):
            debug.event("convert", "a child's exit was reaped elsewhere",    # CrashExit with exitCode 0, Linux only ▸r/conversion-internals
                        program=program, waited_ms=timeout_ms,
                        via="crashexit0")
            return (True, "")

        if (
            process.exitStatus() != QtCore.QProcess.ExitStatus.NormalExit
            or process.exitCode() != 0
        ):
            raw = bytes(process.readAllStandardError())    # iconvert's stderr is the ANSI codepage on Windows ▸r/conversion-internals
            try:
                stderr = raw.decode(
                    locale.getpreferredencoding(False)).strip()
            except (UnicodeDecodeError, LookupError):
                stderr = raw.decode("utf-8", "replace").strip()
            return False, f"exit {process.exitCode()}: {stderr}"

        return True, ""
    finally:
        _reap_or_abandon(process)    # the child is dead before this returns, on every path ▸r/conversion-internals


_ABANDONED: list = []    # killed children that outlived their reap, parked ▸r/conversion-internals


def _reap_or_abandon(process) -> bool:
    """True when dead and reaped; False when parked in `_ABANDONED`. ▸r/conversion-internals"""
    if process.state() == QtCore.QProcess.ProcessState.NotRunning:
        return True
    process.kill()
    if process.waitForFinished(500):
        return True

    def _gone(*_args, process=process):
        try:
            _ABANDONED.remove(process)
        except ValueError:
            return                      # already collected once
        process.deleteLater()

    _ABANDONED.append(process)
    app = QtCore.QCoreApplication.instance()
    if app is not None:    # a finished worker runs no event loop, so `finished` would never arrive there
        process.moveToThread(app.thread())
    process.finished.connect(_gone)
    debug.event("convert", "helper abandoned to the graveyard",
                program=process.program(), args=process.arguments())
    if process.state() == QtCore.QProcess.ProcessState.NotRunning:    # it may have died between the failed wait and the connect, so the signal is never coming
        _gone()
    return False


@functools.lru_cache(maxsize=1)
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


_PILLOW_GUARD = threading.Lock()    # the bomb ceiling is process-global and converters run in threads


def _open_unguarded(source: str):
    """`Image.open` past Pillow's bomb ceiling, lifted for this open only. ▸r/conversion-internals"""
    from PIL import Image

    with _PILLOW_GUARD:
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None    # the file came from the user's own library
        try:
            return Image.open(source)    # open and crop check the ceiling; this path never crops
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


_FIT_ADAPTERS = (    # resamplers only, sips first ▸r/conversion-internals
    ("sips (resampling)", _SIPS_FIT),
    ("pillow", _produce_pillow),
)

_FORMAT_ADAPTERS = (    # Pillow first: it declines fastest ▸r/conversion-internals
    ("pillow", _produce_pillow),
    ("sips (format only)", _SIPS_FORMAT),
    ("iconvert", _produce_iconvert),
)



class _Ctx:
    """One conversion's working state: the contract, the cancel hook, and the attempt trail."""

    def __init__(self, path, size, cancelled, hfs) -> None:
        self.path = path
        self.size = max(1, int(size))
        self._cancelled = cancelled
        self.hfs = hfs if hfs is not None else os.environ.get("HFS", "")
        self.attempts = []
        self.need = ""    # what this file turned out to need; first answer wins ▸r/conversion-internals
        self.fallback = None    # a uniform image kept in case nothing does better ▸p/conversion-shape
        self.fallback_via = ""

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
    """The size contract; called from `_read_qt` and nowhere else. ▸p/conversion-shape"""
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


def _judge(image: QtGui.QImage) -> str:
    """Is an adapter's output acceptable? "" when it is, else why not. ▸p/conversion-shape"""
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
    """Try each adapter, judge it via `reread`, stop at the first good one. ▸r/conversion-internals"""
    for name, produce in adapters:
        if ctx.cancelled():
            return _Step(need=need, reason=REASON_CANCELLED)
        with _scratch_png() as out_path:
            wrote, why = produce(source, out_path, ctx)
            if not wrote:
                if why == "cancelled":
                    ctx.tried(name, why)
                    return _Step(need=need, reason=REASON_CANCELLED)
                ctx.tried(name, why)
                if why == ABANDONED:    # no second converter on a file whose reads are stuck
                    return _Step(need=need, reason=REASON_STALLED)
                continue
            step = reread(out_path, ctx)
            if step.image is None:
                ctx.tried(name, "output unreadable: %s" % (step.reason,))
                continue
            verdict = _judge(step.image)
            if verdict:
                ctx.tried(name, verdict)
                if ctx.fallback is None:
                    ctx.fallback = step.image    # kept, not delivered ▸p/conversion-shape
                    ctx.fallback_via = name
                continue
            via = name    # names both adapters when the read escalated ▸r/conversion-internals
            if step.via and step.via != "qt":
                via = "%s -> %s" % (name, step.via)
            return _Step(image=step.image, via=via)
    return _Step(need=need, reason=REASON_UNREADABLE)


def _fitted(path: str, ctx: _Ctx) -> _Step:
    """Read `path` at the size contract, resampling if Qt refuses. ▸r/conversion-internals"""
    image, declared, error = _read_qt(path, ctx.size)
    if image is not None:
        return _Step(image=image, via="qt")

    declared_mb = _decoded_megabytes(declared)
    if declared_mb <= QtGui.QImageReader.allocationLimit():
        ctx.tried("qt", error or "Qt could not read this file at all")    # a null read is a foreign format or a damaged file alike ▸p/conversion-shape
        ctx.needs(FORMAT)
        return _Step(need=FORMAT, reason=REASON_UNREADABLE)

    ctx.tried("qt", "decode would pass Qt's allocation limit")
    ctx.needs(FIT)
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
        # a resampler's output is read plainly, with no second escalation
        img, _declared, err = _read_qt(produced, inner_ctx.size)
        return _Step(image=img, reason=err or REASON_UNREADABLE)

    return _run_adapters(_FIT_ADAPTERS, path, ctx, FIT, _reread)


def convert_image(path: str, size: int, cancelled=None, hfs=None) -> Conversion:
    """A file on disk to a thumbnail-sized `Conversion`; polls `cancelled`. ▸p/conversion-shape"""
    ctx = _Ctx(path, size, cancelled, hfs)

    step = _fitted(path, ctx)
    if step.image is not None:
        return _answered(ctx, step)
    if step.need != FORMAT:
        return _unanswered(ctx, step.need, step.reason)    # FIT already ran its whole order inside _fitted

    declared_mb = _decoded_megabytes(_exr_size(path))    # Qt declares no size for an EXR; its header does
    if declared_mb > MAX_RESCUE_MEGABYTES:
        debug.event("convert", "image too large to convert - declined",
                    path=path, declared_mb=round(declared_mb),
                    ceiling_mb=MAX_RESCUE_MEGABYTES, why="the EXR header's data window")
        return _unanswered(ctx, FORMAT, REASON_TOO_LARGE)
    step = _run_adapters(_FORMAT_ADAPTERS, path, ctx, FORMAT, _fitted)
    if step.image is not None:
        return _answered(ctx, step)
    return _unanswered(ctx, FORMAT, step.reason)


def _answered(ctx: _Ctx, step: _Step) -> Conversion:
    """Log who answered and why the one before did not, when there was one. ▸p/conversion-shape"""
    if ctx.attempts:
        debug.event("convert", "converted by a fallback",
                    path=ctx.path, via=step.via, need=ctx.need,
                    why=ctx.attempts[0][1], tried=ctx.trail())
    return Conversion(image=step.image, via=step.via, need=ctx.need,
                      attempts=ctx.attempts)


def _unanswered(ctx: _Ctx, need: str, reason: str) -> Conversion:
    """No adapter produced a picture; a kept uniform answer is delivered here. ▸p/conversion-shape"""
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
        return Conversion(need=need, reason=reason, attempts=ctx.attempts)    # browsing away is not a failure and does not belong in the log ▸p/conversion-shape
    if reason != REASON_TOO_LARGE:
        said = ("no thumbnail - a converter stalled on its reads" if reason == REASON_STALLED
                else "no thumbnail - nothing could read it")
        debug.event("convert", said,    # TOO_LARGE has already said its piece, with its ceiling
                    path=ctx.path, need=need,
                    why=ctx.attempts[0][1] if ctx.attempts else "",
                    tried=ctx.trail(),
                    limit_mb=QtGui.QImageReader.allocationLimit(),
                    macos=hostos.is_macos(), pillow=_have_pillow())
    return Conversion(need=need, reason=reason, attempts=ctx.attempts)
