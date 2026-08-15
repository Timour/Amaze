"""The CONVERSION ENGINE - one funnel from a file on disk to a
thumbnail-sized QImage, for every section that shows a picture.

One responsibility, one API: :func:`convert_image`. It returns an
image OR a reason, never a bare None that hides which.

Two different failures, and which one applies is a property of the
IMAGE, measured per file, never of the format - so write no `.hdr` case:

- **FIT** - Qt reads the format but refuses this file's allocation, so
  a converter must resample WHILE converting.
- **FORMAT** - Qt cannot read the format at all. Any converter answers,
  at any size, and the engine scales the result.

The `-Z` that FIT needs silently destroys HDR for FORMAT. ▸r/sips-hdr

Adding an adapter: it writes a PNG and says whether it worked, nothing
more. Never trust its exit code - the engine owns the order, the size
contract and the verification. ▸o/conversion
"""

import contextlib
import functools
import locale
import os
import shutil
import tempfile

from PySide6 import QtCore, QtGui

from amaze.core import debug
from amaze.helpers import hostos


#: What the file needs, decided by measuring it - see the module
#: docstring. Never inferred from the extension.
FIT = "fit"
FORMAT = "format"

#: Why there is no image. A caller that only checks for None cannot
#: tell a cancelled browse from a damaged file, and the difference
#: decides whether the key is retried or marked missing.
REASON_NONE = ""                       # there IS an image
REASON_CANCELLED = "cancelled"
REASON_TOO_LARGE = "too-large"
REASON_UNREADABLE = "unreadable"

#: The most we will inflate an image for, in megabytes decoded.
#:
#: A conversion decodes the WHOLE image before shrinking it - no route
#: avoids that, in-process or out - so the ceiling is what stops a
#: 32K texture (4GB) taking a live Houdini down with it. 1024 covers
#: 16K RGBA (1.07GB) with a little room; past that Amaze declines and
#: SAYS SO, which is the difference between a missing thumbnail and a
#: lost session. The same instinct as the capture that once ran
#: unbounded and ate 86GB.
MAX_RESCUE_MEGABYTES = 1024

#: How long any one converter may run before it is killed.
CONVERT_TIMEOUT_MS = 30000


class Conversion:
    """What :func:`convert_image` answers with.

    Truthy when there is an image. `via` names the adapter that
    produced it, `reason` is one of the REASON_* constants when there
    is none, and `attempts` is the trail - every adapter that was asked
    and what it said - which is what the single log line is built from.
    """

    __slots__ = ("image", "via", "need", "reason", "attempts", "uniform")

    def __init__(self, image=None, via="", need="", reason=REASON_UNREADABLE,
                 attempts=(), uniform=False) -> None:
        self.image = image
        self.via = via
        self.need = need
        self.reason = REASON_NONE if image is not None else reason
        self.attempts = tuple(attempts)
        #: delivered although every pixel is identical - see _judge()
        self.uniform = uniform

    def __bool__(self) -> bool:
        return self.image is not None

    def __repr__(self) -> str:                                # pragma: no cover
        if self.image is not None:
            return "<Conversion %dx%d via %s>" % (
                self.image.width(), self.image.height(), self.via)
        return "<Conversion none: %s>" % (self.reason,)


def _decoded_megabytes(size: QtCore.QSize) -> float:
    """What this image costs fully decoded, at 4 bytes a pixel.

    0 when the format did not declare a size before decoding, which
    reads as "not the size that stopped us" - the honest answer, since
    without a declared size there is nothing to compare.
    """
    if not size.isValid() or size.isEmpty():
        return 0.0
    return size.width() * size.height() * 4 / 1e6


@contextlib.contextmanager
def _scratch_png():
    """THE temp-file lifetime, for every adapter that needs one.

    There were three copies of this before, one per converter, each
    with its own mkstemp, its own finally and its own cleanup log
    line - and the one route that skipped the finally (a terminate()d
    worker) leaked the file from all three.
    """
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            # A transient hold on the fresh temp file (AV/indexer) must
            # not mask the conversion result; the OS reclaims leaked
            # mkstemp files.
            try:
                os.remove(path)
            except OSError:
                debug.event("convert", "temp png cleanup skipped", path=path)


class _Child(QtCore.QProcess):
    """A QProcess that can be told its exit was reaped elsewhere.

    setProcessState is protected in C++; PySide exposes it to a
    subclass, and it is the one door out of the phantom state:
    ~QProcess kills and waits only while the state reads Running, so a
    phantom marked NotRunning destroys in a millisecond instead of
    holding the destructor for its full internal wait (probed live
    2026-08-08 - 0.001s, child untouched).
    """

    def mark_reaped_elsewhere(self):
        self.setProcessState(QtCore.QProcess.ProcessState.NotRunning)


def _run_process(program: str, args: list, timeout_ms: int = CONVERT_TIMEOUT_MS,
                 cancelled=None) -> tuple:
    """Runs a subprocess to completion and returns (success, stderr_text).

    Uses QProcess rather than Python's subprocess module. Houdini on
    macOS is a multi-threaded Cocoa/Qt app, and spawning many child
    processes via Python's fork()-based subprocess from a background
    thread is a known deadlock hazard there: if the fork happens while
    another thread holds a system-library lock (malloc, the ObjC
    runtime), the child inherits that lock frozen and can hang forever in
    the fork-to-exec window, and Python's subprocess does non-trivial
    bookkeeping in that window (pipes/fds for error propagation) which
    widens the risk. QProcess uses Qt's own process-spawning path, which
    keeps that window minimal - safer to call from a Qt worker thread.

    Waits via a scoped QEventLoop rather than QProcess.waitForFinished():
    waitForFinished() is documented to work without a running event loop
    by polling internally, but that polling was found to misbehave on a
    QThread that never calls exec() (as the callers of this function
    don't - they just run a plain Python loop) - iconvert converted a
    real test file in 6.2s when called directly via subprocess.run() from
    the main thread, but the same file consistently hit a hard timeout
    via waitForFinished(). A local QEventLoop, quit from the process's
    finished signal, is the standard Qt idiom for synchronously waiting
    on an async operation from a thread with no persistent event loop of
    its own, and pumps Qt's event system properly regardless."""
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

    # THE WATCHDOG, always on, two checks per 100ms tick.
    #
    # Cancel: a cancelled loader must stop HERE, at the subprocess, not
    # survive to be terminate()d further up - terminating a thread
    # parked in this event loop orphans the child and skips the temp
    # cleanup. Polled, because `cancelled` is set from another thread
    # and this loop is what is blocking.
    #
    # Liveness: Qt hears a child exit through its SIGCHLD handler on
    # this platform, and anything that replaces or ignores that handler
    # leaves the child GONE while the state still reads Running - the
    # wait then burns its whole timeout on a process that finished in
    # milliseconds, which is the measured shape of 18 real files logged
    # as timed out that convert in ~1s by every direct route. Probed
    # live: with the handler sabotaged, a 0.01s echo reported timed out
    # at 3.69s and parked a phantom; restored, 0.08s. A zombie keeps
    # its pid until reaped, so a healthy child can never trip this -
    # the pid vanishing while the state reads Running happens only when
    # the exit was reaped past Qt.
    def _check():
        if cancelled is not None and cancelled():
            state["cancelled"] = True
            _quit()
            return
        pid = int(process.processId() or 0)
        if pid and process.state() != QtCore.QProcess.ProcessState.NotRunning:
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
            # The exit code went with the stolen reap, so the child's
            # WORK is the verdict: every adapter's output feeds
            # _read_qt and the uniform guard - the engine verifying
            # its own output, which also covers the sub-millisecond
            # race where Qt reaped normally and this fired between the
            # reap and the state update. Marked NotRunning so the
            # finally below sees a finished child and nothing is
            # parked, and the destructor is free.
            debug.event("convert", "a child's exit was reaped elsewhere",
                        program=program, waited_ms=timeout_ms)
            process.mark_reaped_elsewhere()
            return (True, "")

        if state["timed_out"]:
            # WHICH TIMEOUT IS THIS? Two very different failures reach
            # here and the record could not tell them apart:
            #
            #   still Running  - the child really is slow or stuck, and
            #                    the timeout is doing its job.
            #   NotRunning     - the child already EXITED and its
            #                    `finished` never reached this loop, so
            #                    a call that was over in a second cost
            #                    the full thirty.
            #
            # Measured 2026-08-08: 18 files logged as timed out, and
            # the same files convert in ~1s from a shell, on the main
            # thread, on a worker thread, at 8-way concurrency, and
            # with the main thread saturated for 40s - none of which
            # reproduces it. Recording the state at the moment of the
            # timeout is what makes the next real occurrence say which
            # of the two it was, instead of being inferred again.
            already_gone = (process.state()
                            == QtCore.QProcess.ProcessState.NotRunning)
            # The FULL path, not a basename: a source scan here bans
            # every name-reading call, because routing by file name is
            # how the decode and fit contracts got confused once. A log
            # line is not worth an exception to that.
            debug.event("convert", "a converter hit its timeout",
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
            # THE THIRD PRESENTATION of a stolen reap. On Linux Qt
            # (6.8.3, pidfd child-watching) a death reaped past Qt
            # still delivers `finished` - but with the status gone:
            # CrashExit and exitCode 0. A real signal death carries
            # its signal number in exitCode (measured 2026-08-14:
            # SIGKILL -> 9; there is no signal 0), so this pair can
            # ONLY mean the exit was reaped elsewhere. Same verdict as
            # the vanished case above - the child's WORK is the
            # verdict - logged with its own door so the record tells
            # the presentations apart. macOS never reaches here for a
            # stolen reap (Qt goes deaf there; the watchdog answers).
            debug.event("convert", "a child's exit was reaped elsewhere",
                        program=program, waited_ms=timeout_ms,
                        via="crashexit0")
            return (True, "")

        if (
            process.exitStatus() != QtCore.QProcess.ExitStatus.NormalExit
            or process.exitCode() != 0
        ):
            # iconvert writes stderr in the platform's ANSI codepage on
            # Windows, not utf-8 - try the locale encoding first.
            raw = bytes(process.readAllStandardError())
            try:
                stderr = raw.decode(
                    locale.getpreferredencoding(False)).strip()
            except (UnicodeDecodeError, LookupError):
                stderr = raw.decode("utf-8", "replace").strip()
            return False, f"exit {process.exitCode()}: {stderr}"

        return True, ""
    finally:
        # THE CHILD IS DEAD BEFORE THIS RETURNS, on every path.
        #
        # `~QProcess()` calls `waitForFinished()` itself, at Qt's
        # DEFAULT thirty-second timeout, when it is destroyed with a
        # live child - and the object dies as soon as this frame does.
        # Every route out of here used to have its own answer to that
        # and three of them had none: `FailedToStart`, a bad exit
        # status, and a clean return all left whatever was running to
        # the destructor. `errorOccurred` also quits the loop above for
        # any error that is NOT FailedToStart, so a crashed or
        # unreadable child arrived here still running.
        #
        # Measured 2026-08-04: a suite that normally takes 134s took
        # 1225s, with 95 `QProcess: Destroyed while process is still
        # running` warnings and three subprocess-timeout tests failing
        # on their deadlines. Intermittent - six consecutive runs
        # before it had zero warnings - which is what a race looks
        # like, and why one guard on every path is the fix rather than
        # one more special case.
        #
        # BOUNDED, and 500ms is not arbitrary: it is what the cancelled
        # path already used, under a shutdown test that asserts the
        # whole of `engine.shutdown()` finishes in under two seconds.
        # `kill()` is SIGKILL, so a reap is milliseconds - but a child
        # inside uninterruptible disk I/O, which is exactly what sips
        # and iconvert do, has its SIGKILL DEFERRED, and an unbounded
        # wait here would spend that budget on the one case nothing can
        # hurry. If the child outlives the bound the destructor still
        # blocks, as it does today: this makes that the rare case
        # instead of the routine one on three unguarded paths.
        _reap_or_abandon(process)


#: Killed children that survived their reap: a process in
#: uninterruptible disk I/O defers even SIGKILL, and ~QProcess blocks
#: up to thirty seconds waiting for it. Parked here, each cleans
#: itself up whenever the kernel lets go, and the caller returned in
#: half a second. Measured 2026-08-08: a suite of 134s ran 1211s with
#: 71 such children, each stalling its frame the full thirty.
#:
#: WHAT THIS DOES NOT FIX, measured the same day with two stack
#: samples: the cost MOVES to interpreter shutdown. `_Py_Finalize`
#: runs PySide's cleanup, which walks every living QObject and
#: destroys it - so anything still parked here pays the full
#: ~QProcess wait then, after the suite has already printed its
#: result. Two runs sat in `poll()` for eleven and twenty minutes
#: with the tests long finished. The run is fast; the exit is not.
#: The cure is upstream of both - not spawning a child that cannot
#: succeed twice (the thumbnail-failure memory).
_ABANDONED: list = []


def _reap_or_abandon(process) -> bool:
    """True = the child is dead and reaped. False = it outlived
    SIGKILL's half-second grace and was handed to the graveyard so
    THIS frame returns now instead of the destructor blocking."""
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
    # It may have died between the failed wait and the connect - the
    # signal is then never coming, so collect it here.
    if process.state() == QtCore.QProcess.ProcessState.NotRunning:
        _gone()
    return False


@functools.lru_cache(maxsize=1)
def _have_pillow() -> bool:
    """Is Pillow importable in THIS Houdini's Python?

    It ships with Houdini 22 (12.1.0, measured), but a stripped or
    older install is not something to find out about by raising inside
    a thumbnail worker. Cached: the answer cannot change mid-session,
    and this is asked once per oversized image.
    """
    try:
        import PIL.Image                                      # noqa: F401
    except Exception:                                         # noqa: BLE001
        return False
    return True


# -- the adapters. They ONLY produce. ---------------------------------
#
# Each takes (source, out_path, ctx) and returns (wrote_it, why_not).
# None of them loads, judges, orders, falls back or logs.


def _produce_sips(source: str, out_path: str, ctx, resample: bool) -> tuple:
    """macOS's own ImageIO converter, /usr/bin/sips.

    Registered TWICE, deliberately, because the two registrations are
    two different commands and the difference is the whole bug:

    - `-Z <size>` resamples while converting. Mandatory on the FIT
      route - the point is to never write a full-size temp file.
    - without it, sips converts and nothing else. That is the FORMAT
      route, and it is the ONLY one that decodes Radiance .hdr
      correctly.

    sips is part of the base macOS install (root-owned, on the system
    volume, not an Xcode tool), so absence is not the realistic macOS
    failure - failing on a FILE is: exit 13 with no output on a format
    ImageIO does not know, such as Houdini's own .rat (research.md).
    That is why the order continues past it.
    """
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
    """Houdini's own converter - the same libraries Houdini itself
    reads textures with, so it is the guaranteed-correct answer for
    every format Houdini knows, .rat included.

    FORMAT only. It converts formats and has no resize option at all
    (measured 2026-08-01), so on the FIT route its full-size output is
    refused by Qt all over again - it cannot help there, and offering
    it would only spend a Houdini process startup to fail.
    """
    iconvert = hostos.bundled_binary(ctx.hfs, "iconvert")
    if iconvert is None:
        return False, "iconvert not in $HFS/bin"
    ok, err = _run_process(iconvert, [source, out_path], cancelled=ctx.cancelled)
    return (True, "") if ok else (False, err)


def _produce_pillow(source: str, out_path: str, ctx) -> tuple:
    """Resample with the Pillow that ships inside Houdini's own Python.

    This is the route for the machines that have no sips - every
    Windows and Linux artist. An 8K displacement map decodes to 268MB,
    past Qt's 256MB refusal, and 8K displacement maps are ordinary in a
    VFX library; before this those artists got no thumbnail at all.

    reduce() FIRST, then the final resize. reduce() is an integer box
    downsample and does the expensive shrink cheaply: measured on a
    9000x9000 PNG, 0.66s this way against 1.51s for a plain BILINEAR
    thumbnail - and 2.46s for thumbnail(reducing_gap=...), which is the
    API documented as the fast path and is the slowest of the three.
    draft() is not used because it is JPEG-only, and a JPEG rarely
    reaches here: Qt's scaled read handles those, libjpeg scaling while
    it decompresses.

    In the FORMAT order it is last and usually declines - PIL reads no
    EXR, no Radiance HDR and no .rat - but it does read TGA, which is
    a real answer on the platforms with no sips.
    """
    if not _have_pillow():
        return False, "no Pillow in this Houdini's Python"
    try:
        from PIL import Image

        # Pillow refuses a large image by default as a decompression
        # bomb (~179M pixels). The file came from the user's own
        # library, and refusing it here would reintroduce exactly the
        # silence this engine exists to end.
        previous = Image.MAX_IMAGE_PIXELS
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
        # getattr, because the two shipped Pillows straddle an API
        # break: `Image.Resampling` arrived in 9.1, H21's Python has
        # 9.0.1 and H22's has 12.1 (research.md > Windows). The enum
        # spelling raised AttributeError on H21, the blanket except
        # below read that as `unreadable`, and every oversized image on
        # an H21 machine with no sips - every H21 Windows artist - got
        # no thumbnail. Both spellings measure to the same value.
        resample = getattr(Image, "Resampling", Image).BILINEAR
        image.thumbnail((ctx.size, ctx.size), resample)
        image.convert("RGB").save(out_path, "PNG")
    except Exception as exc:                                  # noqa: BLE001
        return False, str(exc)
    return True, ""


_SIPS_FIT = functools.partial(_produce_sips, resample=True)
_SIPS_FORMAT = functools.partial(_produce_sips, resample=False)


#: The FIT order: resamplers only. sips is measured at 0.21s on a
#: 9000x9000 PNG against Pillow's 0.66s for the same quality, and it
#: runs out of process so Houdini keeps none of the memory
#: (research.md). Pillow is not an upgrade to sips - it is the route
#: for the platforms that have no sips.
_FIT_ADAPTERS = (
    ("sips (resampling)", _SIPS_FIT),
    ("pillow", _produce_pillow),
)

#: The FORMAT order: anything that writes a Qt-readable file. PILLOW
#: FIRST, measured 2026-08-07 on a real 117MB camera TIFF: pillow
#: answered in 0.3s while sips and iconvert each burned their full
#: 30s timeout in front of it - a two-minute thumbnail for a
#: photographer's ordinary file. A pillow decline costs milliseconds
#: (in-process, no subprocess, no timeout to wait out), so the
#: formats pillow cannot read - EXR, HDR, DNG - fall through to sips
#: (~0.08s EXR, ~2.3s DNG) and then iconvert at the old speed.
_FORMAT_ADAPTERS = (
    ("pillow", _produce_pillow),
    ("sips (format only)", _SIPS_FORMAT),
    ("iconvert", _produce_iconvert),
)

# There was a "Force iconvert only" preference here, and a second
# FORMAT order to serve it. It was the MANUAL WORKAROUND for a
# converter that returned a wrong picture and reported success - the
# engine catches that itself now, refuses the answer and moves to the
# next adapter, so the question it asked the user has no answer left to
# give. Removed 2026-08-03. There is ONE order.


# -- the engine -------------------------------------------------------


class _Ctx:
    """One conversion's working state: the contract, the cancel hook,
    and the trail every attempt writes into."""

    def __init__(self, path, size, cancelled, hfs) -> None:
        self.path = path
        self.size = max(1, int(size))
        self._cancelled = cancelled
        self.hfs = hfs if hfs is not None else os.environ.get("HFS", "")
        self.attempts = []
        #: What this file turned out to need, recorded where it is
        #: MEASURED rather than reconstructed at the end. First answer
        #: wins: a foreign format whose converted temp is then oversized
        #: needed FORMAT, and the `via` string names both halves.
        self.need = ""
        #: a uniform image kept in case nothing does better - see _judge
        self.fallback = None
        self.fallback_via = ""

    def needs(self, need: str) -> None:
        if not self.need:
            self.need = need

    def cancelled(self) -> bool:
        return self._cancelled is not None and self._cancelled()

    #: A converter's stderr can be four lines of libpng chatter. The
    #: trail is a log line, not a transcript - keep it readable, on one
    #: line, and let whoever needs the whole thing run the tool.
    WHY_LIMIT = 160

    def tried(self, name: str, why: str) -> None:
        why = " ".join((why or "").split())
        if len(why) > self.WHY_LIMIT:
            why = why[:self.WHY_LIMIT - 1] + "…"
        self.attempts.append((name, why))

    def trail(self) -> str:
        return "; ".join("%s: %s" % (n, w or "no answer")
                         for n, w in self.attempts)


class _Step:
    """What one read attempt came back with: an image, or the NEED that
    stopped it plus a reason."""

    __slots__ = ("image", "via", "need", "reason", "uniform")

    def __init__(self, image=None, via="", need="", reason=REASON_UNREADABLE,
                 uniform=False) -> None:
        self.image = image
        self.via = via
        self.need = need
        self.reason = reason
        self.uniform = uniform


def _fit_to_contract(image: QtGui.QImage, size: int) -> QtGui.QImage:
    """The size contract, in ONE place: nothing leaves this engine
    larger than what was asked for. An adapter that resamples has
    already done it; one that only converts has not.

    Called from `_read_qt` and nowhere else, deliberately. Every image
    this engine returns - a plain read, a resampled rescue, a converted
    temp - comes back through that one function, so the contract has a
    single site that a test can hold. It had three, and with three
    none of them is load-bearing: removing any one left the suite green
    (measured while sabotage-verifying this batch), which is the same
    shape as the delegate list written out by hand in three places.
    """
    if image.width() <= size and image.height() <= size:
        return image
    return image.scaled(
        size, size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


def _uniform(image: QtGui.QImage) -> bool:
    """Is every pixel of this image identical?

    Measured on an 8x8 smooth downsample, which averages: a picture
    with any structure at all leaves two of those 64 blocks differing,
    and a solid fill leaves none. Exact equality, never a tolerance -
    a near-uniform photograph of a wall is a real picture and must not
    be thrown away.

    Cheap on purpose: 64 pixel reads per converted file, against the
    seconds a converter costs.
    """
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
    """Is an ADAPTER's output acceptable? "" when it is, else why not.

    Only converter output is judged. A Qt read of a format Qt supports
    is the ground truth here - there is no second decoder that would do
    better on it, and a flat PNG is simply a flat PNG.

    A uniform image is a SUSPICION, not a verdict. `sips -Z` on a
    Radiance .hdr returns exit 0 and a solid black picture, which is
    the failure this whole engine is built around - but a genuinely
    black texture exists too, and refusing to show it would trade 178
    black tiles for 178 missing ones. So the engine tries the next
    adapter and keeps this answer; if nothing does better, the flat
    image IS the file and it is delivered, with the log saying so.
    """
    if image is None or image.isNull():
        return "null image"
    if image.width() <= 0 or image.height() <= 0:
        return "empty image"
    if _uniform(image):
        return "every pixel identical - no picture in it"
    return ""


def _read_qt(path: str, size: int) -> tuple:
    """The Qt-native adapter: decode in process, SCALED, never whole.

    `QImage(path)` decodes every pixel into memory first, and Qt
    refuses any image whose full decode would pass its 256MB allocation
    limit - it returns a null image and raises nothing. A 24000x12000
    JPEG needs 1152MB, so every 24K texture silently had no thumbnail
    and no log line to say why (measured 2026-08-01 on a real 72MB
    file). setScaledSize asks the decoder for the small image directly -
    libjpeg scales while decoding - so the memory never appears. It is
    also faster for ordinary images, which is why this is the one path
    rather than a big-file special case.

    Returns (image_or_None, declared_size, error_text).
    """
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
    # The reader could not say how big it is (some formats do not
    # declare a size before decoding). Fall back to the whole-image
    # read, which still works for anything under the limit - and comes
    # back FULL SIZE, which is why the contract is applied here rather
    # than at the callers.
    whole = QtGui.QImage(path)
    if not whole.isNull():
        return _fit_to_contract(whole, size), declared, ""
    return None, declared, reader.errorString()


def _run_adapters(adapters, source: str, ctx: _Ctx, need: str,
                  reread) -> _Step:
    """Ask each adapter in turn, LOAD and JUDGE what it produced, stop
    at the first acceptable answer.

    `reread` is how the produced file is read back. On the FORMAT route
    that is the full fitted read, because a converter that only
    converts can write a temp PNG which is itself past Qt's limit (an
    8K HDR converts to 268MB of PNG) - so the temp then needs the FIT
    route, and gets it, from the same measurement as any other file.
    """
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
                    # Kept, not delivered - see _judge().
                    ctx.fallback = step.image
                    ctx.fallback_via = name
                continue
            # NAME BOTH, when the read escalated: a full-size temp PNG
            # from a FORMAT converter can itself be past Qt's limit
            # (an 8K HDR converts to 268MB of PNG), and then a FIT
            # adapter carried the second half. "who answered" is both
            # of them.
            via = name
            if step.via and step.via != "qt":
                via = "%s -> %s" % (name, step.via)
            return _Step(image=step.image, via=via)
    return _Step(need=need, reason=REASON_UNREADABLE)


def _fitted(path: str, ctx: _Ctx) -> _Step:
    """Read `path` at the size contract, resampling out of process if
    Qt refuses the decode.

    This is where DECODE and FIT are told apart, by measurement:
    a declared size whose decode passes Qt's own allocation limit is
    FIT; anything else Qt could not read is FORMAT. Called for the
    source file AND for whatever a FORMAT adapter produced, so an
    oversized temp is handled by the same rule that handles an
    oversized source.
    """
    image, declared, error = _read_qt(path, ctx.size)
    if image is not None:
        return _Step(image=image, via="qt")

    declared_mb = _decoded_megabytes(declared)
    if declared_mb <= QtGui.QImageReader.allocationLimit():
        # SAY WHICH FAILURE THIS IS. This branch is reached by any read
        # that came back null - a foreign format, but also a truncated
        # download or a corrupt PNG. A log line that names the wrong
        # cause is worse than none: it sends the next person measuring
        # allocation limits for a file that is simply damaged.
        ctx.tried("qt", error or "Qt could not read this file at all")
        ctx.needs(FORMAT)
        return _Step(need=FORMAT, reason=REASON_UNREADABLE)

    ctx.tried("qt", "decode would pass Qt's allocation limit")
    ctx.needs(FIT)
    if declared_mb > MAX_RESCUE_MEGABYTES:
        # DECLINED ON PURPOSE, and loudly. Every route inflates the
        # whole image first, so going ahead here risks the user's
        # scene, not just this tile.
        debug.event(
            "convert", "image too large to convert - declined",
            path=path, declared_mb=round(declared_mb),
            ceiling_mb=MAX_RESCUE_MEGABYTES,
            why="decode would pass Qt's allocation limit",
            note="a conversion decodes the whole image before shrinking "
                 "it; past the ceiling that risks the session")
        return _Step(need=FIT, reason=REASON_TOO_LARGE)

    def _reread(produced, inner_ctx):
        # A resampler's output is already small - a plain read, and no
        # second escalation, so a bad temp can never loop back into the
        # converter that produced it.
        img, _declared, err = _read_qt(produced, inner_ctx.size)
        return _Step(image=img, reason=err or REASON_UNREADABLE)

    return _run_adapters(_FIT_ADAPTERS, path, ctx, FIT, _reread)


def convert_image(path: str, size: int, cancelled=None, hfs=None) -> Conversion:
    """THE funnel. A file on disk to a thumbnail-sized QImage.

    `cancelled` is a callable polled from inside the converters' event
    loop - a user browsing away must stop the subprocess HERE, not
    survive to be terminate()d further up, which orphans the child and
    leaks its temp file. `hfs` locates Houdini's bundled iconvert and
    defaults to $HFS.

    There is no knob. The order is the engine's, decided once from
    measurements, and every adapter's answer is verified - which is
    what retired the Preferences toggle that used to reorder it.

    Always returns a :class:`Conversion`: an image, or a REASON.
    """
    ctx = _Ctx(path, size, cancelled, hfs)

    step = _fitted(path, ctx)
    if step.image is not None:
        return _answered(ctx, step)
    if step.need != FORMAT:
        # FIT has already run its whole order inside _fitted; there is
        # no format conversion that would help an image Qt can read.
        return _unanswered(ctx, step.need, step.reason)

    step = _run_adapters(_FORMAT_ADAPTERS, path, ctx, FORMAT, _fitted)
    if step.image is not None:
        return _answered(ctx, step)
    return _unanswered(ctx, FORMAT, step.reason)


def _answered(ctx: _Ctx, step: _Step) -> Conversion:
    """ONE log line, naming who answered and why the one before it did
    not - and only when there WAS one before it. Every ordinary PNG
    answers on the first attempt, and a line per tile would flood the
    log rather than inform it.

    The message is constant and the path rides as data, so event()'s
    flood guard can collapse a whole folder of the same story.
    """
    if ctx.attempts:
        debug.event("convert", "converted by a fallback",
                    path=ctx.path, via=step.via, need=ctx.need,
                    why=ctx.attempts[0][1], tried=ctx.trail())
    return Conversion(image=step.image, via=step.via, need=ctx.need,
                      attempts=ctx.attempts)


def _unanswered(ctx: _Ctx, need: str, reason: str) -> Conversion:
    """No adapter produced a picture.

    A kept uniform answer is delivered here rather than thrown away -
    if every adapter says the image is one flat colour, that is what
    the image is.
    """
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
        # Browsing away is not a failure and does not belong in the log.
        return Conversion(need=need, reason=reason, attempts=ctx.attempts)
    if reason != REASON_TOO_LARGE:
        # TOO_LARGE has already said its piece, with its ceiling.
        debug.event("convert", "no thumbnail - nothing could read it",
                    path=ctx.path, need=need,
                    why=ctx.attempts[0][1] if ctx.attempts else "",
                    tried=ctx.trail(),
                    limit_mb=QtGui.QImageReader.allocationLimit(),
                    macos=hostos.is_macos(), pillow=_have_pillow())
    return Conversion(need=need, reason=reason, attempts=ctx.attempts)
