"""The CONVERSION ENGINE - one funnel from a file on disk to a thumbnail-sized QImage, answering with an image OR a reason. FIT and FORMAT are properties of the FILE, measured per file, never of the extension. ▸o/conversion ▸p/conversion-shape ▸r/conversion-internals"""

import contextlib
import functools
import locale
import os
import shutil
import tempfile

from PySide6 import QtCore, QtGui

from amaze.core import debug
from amaze.helpers import hostos


FIT = "fit"    # what the file needs, decided by MEASURING it, never inferred from the extension ▸r/conversion-internals
FORMAT = "format"

REASON_NONE = ""                       # there IS an image; the rest tell a cancelled browse from a damaged file, which decides retry vs missing ▸p/conversion-shape
REASON_CANCELLED = "cancelled"
REASON_TOO_LARGE = "too-large"
REASON_UNREADABLE = "unreadable"

MAX_RESCUE_MEGABYTES = 1024    # the most we inflate for, decoded: every route decodes the WHOLE image first, so this is what stops a 32K texture taking a live Houdini down ▸r/conversion-internals

CONVERT_TIMEOUT_MS = 30000    # how long any one converter may run before it is killed


class Conversion:
    """What :func:`convert_image` answers with - truthy when there is an image, `via` naming the adapter, `reason` a REASON_* when there is none, `attempts` the trail the log line is built from."""

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
    """What this image costs fully decoded, at 4 bytes a pixel - 0 when the format declared no size, which reads as size-was-not-the-cause. ▸r/conversion-internals"""
    if not size.isValid() or size.isEmpty():
        return 0.0
    return size.width() * size.height() * 4 / 1e6


@contextlib.contextmanager
def _scratch_png():
    """THE temp-file lifetime, for every adapter that needs one. ▸p/conversion-shape"""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            try:    # a transient hold on the fresh temp (AV, indexer) must not mask the conversion result; the OS reclaims leaked mkstemp files ▸p/conversion-shape
                os.remove(path)
            except OSError:
                debug.event("convert", "temp png cleanup skipped", path=path)


class _Child(QtCore.QProcess):
    """A QProcess that can be told its exit was reaped elsewhere - `setProcessState` is the one door out of the phantom state. ▸r/conversion-internals"""

    def mark_reaped_elsewhere(self):
        self.setProcessState(QtCore.QProcess.ProcessState.NotRunning)


def _run_process(program: str, args: list, timeout_ms: int = CONVERT_TIMEOUT_MS,
                 cancelled=None) -> tuple:
    """Run a subprocess to completion, returning (success, stderr_text) - QProcess not `subprocess`, waited on a scoped QEventLoop not `waitForFinished()`, both for measured reasons. ▸r/conversion-internals"""
    process = _Child()
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

    def _check():    # THE WATCHDOG, always on: cancel (which must stop HERE, at the subprocess) and liveness (a child reaped past Qt reads Running forever) ▸r/conversion-internals
        if cancelled is not None and cancelled():
            state["cancelled"] = True
            _quit()
            return
        pid = int(process.processId() or 0)
        if (pid and not hostos.is_windows()    # `os.kill(pid, 0)` is not a liveness probe on Windows - every signal but CTRL_C/CTRL_BREAK runs TerminateProcess and sets the exit code to the signal, so a 0 would kill the converter and make it look successful ▸r/os-kill-windows
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
            debug.event("convert", "a child's exit was reaped elsewhere",    # the exit code went with the reap, so the child's WORK is the verdict; marked NotRunning so the destructor is free ▸r/conversion-internals
                        program=program, waited_ms=timeout_ms)
            process.mark_reaped_elsewhere()
            return (True, "")

        if state["timed_out"]:
            already_gone = (process.state()    # WHICH TIMEOUT IS THIS? still Running = genuinely stuck; NotRunning = it exited and `finished` never arrived, so a one-second call cost thirty ▸p/conversion-shape
                            == QtCore.QProcess.ProcessState.NotRunning)
            debug.event("convert", "a converter hit its timeout",    # the FULL path, not a basename: a source scan bans name-reading calls here ▸r/conversion-internals
                        program=program,
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
            debug.event("convert", "a child's exit was reaped elsewhere",    # THE THIRD PRESENTATION: CrashExit with exitCode 0, which no real signal death produces - Linux only ▸r/conversion-internals
                        program=program, waited_ms=timeout_ms,
                        via="crashexit0")
            return (True, "")

        if (
            process.exitStatus() != QtCore.QProcess.ExitStatus.NormalExit
            or process.exitCode() != 0
        ):
            raw = bytes(process.readAllStandardError())    # iconvert writes stderr in the platform's ANSI codepage on Windows, not utf-8 ▸r/conversion-internals
            try:
                stderr = raw.decode(
                    locale.getpreferredencoding(False)).strip()
            except (UnicodeDecodeError, LookupError):
                stderr = raw.decode("utf-8", "replace").strip()
            return False, f"exit {process.exitCode()}: {stderr}"

        return True, ""
    finally:
        _reap_or_abandon(process)    # THE CHILD IS DEAD BEFORE THIS RETURNS, on every path - `~QProcess()` otherwise blocks thirty seconds ▸r/conversion-internals


_ABANDONED: list = []    # killed children that survived their reap, parked so the caller returns in half a second instead of waiting on a deferred SIGKILL - the cost then MOVES to interpreter shutdown ▸r/conversion-internals


def _reap_or_abandon(process) -> bool:
    """True = dead and reaped; False = it outlived SIGKILL's half-second grace and went to the graveyard so THIS frame returns now. ▸r/conversion-internals"""
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
    process.finished.connect(_gone)
    debug.event("convert", "helper abandoned to the graveyard",
                program=process.program())
    if process.state() == QtCore.QProcess.ProcessState.NotRunning:    # it may have died between the failed wait and the connect, so the signal is never coming
        _gone()
    return False


@functools.lru_cache(maxsize=1)
def _have_pillow() -> bool:
    """Is Pillow importable in THIS Houdini's Python? Cached - the answer cannot change mid-session, and a stripped install must not be found out about by raising inside a worker. ▸r/conversion-internals"""
    try:
        import PIL.Image                                      # noqa: F401
    except Exception:                                         # noqa: BLE001
        return False
    return True




def _produce_sips(source: str, out_path: str, ctx, resample: bool) -> tuple:
    """macOS's own ImageIO converter, `/usr/bin/sips` - registered TWICE because `-Z` resamples (FIT) and its absence is the ONLY correct Radiance `.hdr` decode (FORMAT). ▸r/sips-hdr ▸r/conversion-internals"""
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
    """Houdini's own converter, correct for every format Houdini reads including `.rat` - FORMAT only, since it has no resize option at all. ▸r/conversion-internals"""
    iconvert = hostos.bundled_binary(ctx.hfs, "iconvert")
    if iconvert is None:
        return False, "iconvert not in $HFS/bin"
    ok, err = _run_process(iconvert, [source, out_path], cancelled=ctx.cancelled)
    return (True, "") if ok else (False, err)


def _produce_pillow(source: str, out_path: str, ctx) -> tuple:
    """Resample with the Pillow inside Houdini's own Python - the route for every machine with no sips. `reduce()` FIRST, then the final resize. ▸r/conversion-internals"""
    if not _have_pillow():
        return False, "no Pillow in this Houdini's Python"
    try:
        from PIL import Image

        previous = Image.MAX_IMAGE_PIXELS    # Pillow refuses ~179M pixels as a decompression bomb, but this file came from the user's own library ▸r/conversion-internals
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(source) as opened:
                factor = max(1, min(opened.width // max(ctx.size, 1),
                                    opened.height // max(ctx.size, 1)))
                image = opened.reduce(factor) if factor > 1 else opened.copy()
        finally:
            Image.MAX_IMAGE_PIXELS = previous

        if ctx.cancelled():
            return False, "cancelled"
        resample = getattr(Image, "Resampling", Image).BILINEAR    # H21's Pillow 9.0.1 and H22's 12.1 straddle the `Image.Resampling` break; both spellings measure the same ▸r/conversion-internals
        image.thumbnail((ctx.size, ctx.size), resample)
        image.convert("RGB").save(out_path, "PNG")
    except Exception as exc:                                  # noqa: BLE001
        return False, str(exc)
    return True, ""


_SIPS_FIT = functools.partial(_produce_sips, resample=True)
_SIPS_FORMAT = functools.partial(_produce_sips, resample=False)


_FIT_ADAPTERS = (    # resamplers ONLY, sips first at 0.21s against Pillow's 0.66s - Pillow is not an upgrade, it is the route for platforms with no sips ▸r/conversion-internals
    ("sips (resampling)", _SIPS_FIT),
    ("pillow", _produce_pillow),
)

_FORMAT_ADAPTERS = (    # PILLOW FIRST: it declines in milliseconds in-process, where sips and iconvert each burn a full 30s timeout ahead of it ▸r/conversion-internals
    ("pillow", _produce_pillow),
    ("sips (format only)", _SIPS_FORMAT),
    ("iconvert", _produce_iconvert),
)



class _Ctx:
    """One conversion's working state: the contract, the cancel hook, and the trail every attempt writes into."""

    def __init__(self, path, size, cancelled, hfs) -> None:
        self.path = path
        self.size = max(1, int(size))
        self._cancelled = cancelled
        self.hfs = hfs if hfs is not None else os.environ.get("HFS", "")
        self.attempts = []
        self.need = ""    # what this file turned out to need, recorded where it is MEASURED; first answer wins ▸r/conversion-internals
        self.fallback = None    # a uniform image kept in case nothing does better ▸p/conversion-shape
        self.fallback_via = ""

    def needs(self, need: str) -> None:
        if not self.need:
            self.need = need

    def cancelled(self) -> bool:
        return self._cancelled is not None and self._cancelled()

    WHY_LIMIT = 160    # a converter's stderr can be four lines of libpng chatter, and the trail is a log line, not a transcript ▸p/conversion-shape

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
    """The size contract, in ONE place - called from `_read_qt` and nowhere else, so every image the engine returns passes it. ▸p/conversion-shape"""
    if image.width() <= size and image.height() <= size:
        return image
    return image.scaled(
        size, size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


def _uniform(image: QtGui.QImage) -> bool:
    """Is every pixel identical? Measured on an 8x8 smooth downsample, exact equality and never a tolerance - a near-uniform photograph of a wall is a real picture. ▸r/conversion-internals"""
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
    """Is an ADAPTER's output acceptable? "" when it is, else why not - a uniform image is a SUSPICION, not a verdict, and only converter output is judged. ▸p/conversion-shape"""
    if image is None or image.isNull():
        return "null image"
    if image.width() <= 0 or image.height() <= 0:
        return "empty image"
    if _uniform(image):
        return "every pixel identical - no picture in it"
    return ""


def _read_qt(path: str, size: int) -> tuple:
    """The Qt-native adapter: decode in process, SCALED, never whole - returns (image_or_None, declared_size, error_text). ▸r/conversion-internals"""
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
    whole = QtGui.QImage(path)    # the reader declared no size, so fall back to the whole-image read - which comes back FULL SIZE, and is why the contract is applied here ▸r/conversion-internals
    if not whole.isNull():
        return _fit_to_contract(whole, size), declared, ""
    return None, declared, reader.errorString()


def _run_adapters(adapters, source: str, ctx: _Ctx, need: str,
                  reread) -> _Step:
    """Ask each adapter in turn, LOAD and JUDGE what it produced, stop at the first acceptable answer - `reread` is how the produced file is read back. ▸r/conversion-internals"""
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
            via = name    # NAME BOTH when the read escalated: a FORMAT converter's temp can itself be past Qt's limit, and a FIT adapter carried the second half ▸r/conversion-internals
            if step.via and step.via != "qt":
                via = "%s -> %s" % (name, step.via)
            return _Step(image=step.image, via=via)
    return _Step(need=need, reason=REASON_UNREADABLE)


def _fitted(path: str, ctx: _Ctx) -> _Step:
    """Read `path` at the size contract, resampling out of process if Qt refuses the decode - this is where FIT and FORMAT are told apart, by measurement. ▸r/conversion-internals"""
    image, declared, error = _read_qt(path, ctx.size)
    if image is not None:
        return _Step(image=image, via="qt")

    declared_mb = _decoded_megabytes(declared)
    if declared_mb <= QtGui.QImageReader.allocationLimit():
        ctx.tried("qt", error or "Qt could not read this file at all")    # SAY WHICH FAILURE THIS IS - a null read is a foreign format, a truncated download or a corrupt PNG alike ▸p/conversion-shape
        ctx.needs(FORMAT)
        return _Step(need=FORMAT, reason=REASON_UNREADABLE)

    ctx.tried("qt", "decode would pass Qt's allocation limit")
    ctx.needs(FIT)
    if declared_mb > MAX_RESCUE_MEGABYTES:
        debug.event(    # DECLINED ON PURPOSE, and loudly: every route inflates the whole image first, so going ahead risks the user's scene ▸p/conversion-shape
            "convert", "image too large to convert - declined",
            path=path, declared_mb=round(declared_mb),
            ceiling_mb=MAX_RESCUE_MEGABYTES,
            why="decode would pass Qt's allocation limit",
            note="a conversion decodes the whole image before shrinking "
                 "it; past the ceiling that risks the session")
        return _Step(need=FIT, reason=REASON_TOO_LARGE)

    def _reread(produced, inner_ctx):
        # a resampler's output is already small: a plain read and no second escalation, so a bad temp cannot loop back into the converter that produced it
        img, _declared, err = _read_qt(produced, inner_ctx.size)
        return _Step(image=img, reason=err or REASON_UNREADABLE)

    return _run_adapters(_FIT_ADAPTERS, path, ctx, FIT, _reread)


def convert_image(path: str, size: int, cancelled=None, hfs=None) -> Conversion:
    """THE funnel: a file on disk to a thumbnail-sized QImage, always answering with a `Conversion`. `cancelled` is polled inside the converters' event loop; `hfs` defaults to $HFS. ▸p/conversion-shape"""
    ctx = _Ctx(path, size, cancelled, hfs)

    step = _fitted(path, ctx)
    if step.image is not None:
        return _answered(ctx, step)
    if step.need != FORMAT:
        return _unanswered(ctx, step.need, step.reason)    # FIT already ran its whole order inside _fitted, and no format conversion helps an image Qt can read

    step = _run_adapters(_FORMAT_ADAPTERS, path, ctx, FORMAT, _fitted)
    if step.image is not None:
        return _answered(ctx, step)
    return _unanswered(ctx, FORMAT, step.reason)


def _answered(ctx: _Ctx, step: _Step) -> Conversion:
    """ONE log line naming who answered and why the one before it did not - only when there WAS one before it, message constant and path as data so the flood guard can collapse a folder. ▸p/conversion-shape"""
    if ctx.attempts:
        debug.event("convert", "converted by a fallback",
                    path=ctx.path, via=step.via, need=ctx.need,
                    why=ctx.attempts[0][1], tried=ctx.trail())
    return Conversion(image=step.image, via=step.via, need=ctx.need,
                      attempts=ctx.attempts)


def _unanswered(ctx: _Ctx, need: str, reason: str) -> Conversion:
    """No adapter produced a picture - a kept uniform answer is delivered here rather than thrown away. ▸p/conversion-shape"""
    if reason == REASON_UNREADABLE and ctx.fallback is not None:
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
        debug.event("convert", "no thumbnail - nothing could read it",    # TOO_LARGE has already said its piece, with its ceiling
                    path=ctx.path, need=need,
                    why=ctx.attempts[0][1] if ctx.attempts else "",
                    tried=ctx.trail(),
                    limit_mb=QtGui.QImageReader.allocationLimit(),
                    macos=hostos.is_macos(), pillow=_have_pillow())
    return Conversion(need=need, reason=reason, attempts=ctx.attempts)
