"""Material thumbnails rendered by ONE husk in the background, a frame each. ▸r/husk-startup"""
import atexit
import collections
import os
import queue
import shutil
import subprocess
import threading

import hou
from PySide6 import QtCore

from amaze.core import debug

DELEGATES = {"Karma": "BRAY_HdKarma", "Octane": "HdOctaneRendererPlugin"}
UNUSED_PLUGINS = {    # Houdini plugins a thumbnail husk skips; Octane aborts without its own
    "Karma": ("redshift4houdini.*", "Houdini_Octane*"),
    "Octane": ("redshift4houdini.*",),
}
RESTART_EVERY = {"Octane": 1}    # Octane keeps frame 1's material unless restarted
PROGRESS = "ALF_PROGRESS"
DONE = "AMAZE_FRAME_DONE"
EXCLUDE = "HOUDINI_DSO_EXCLUDE_PATTERN"

PREFRAME = '''from pxr import UsdShade
import hou
_prims = %(prims)r
_mat = UsdShade.Material(stage.GetPrimAtPath(_prims[int(hou.frame()) - 1]))
UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(%(ball)r)).Bind(
    _mat, UsdShade.Tokens.weakerThanDescendants)
'''

POSTFRAME = '''import os
import hou
_frame = int(hou.frame())
for _name in ("frame.%%04d.exr" %% _frame, "frame.$F4.exr"):    # Karma expands $F4, Octane not
    _path = os.path.join(%(dir)r, _name)
    if os.path.exists(_path):
        os.replace(_path, os.path.join(%(dir)r, "f%%d.exr" %% _frame))
        break
print("%(done)s %%d" %% _frame, flush=True)
'''


def plugin_exclusion(renderer: str, current: str = "") -> str:
    """HOUDINI_DSO_EXCLUDE_PATTERN for a `renderer` husk, keeping a pattern already set."""
    patterns = list(UNUSED_PLUGINS.get(renderer, ()))
    if current and "{" not in current:
        patterns.insert(0, current)
    elif current:
        return current    # a braced pattern of the user's own cannot be nested; it wins
    if not patterns:
        return ""
    return patterns[0] if len(patterns) == 1 else "{%s}" % ",".join(patterns)


def _script_arg(path: str) -> str:
    """husk splits a script argument like a command line, so a path with a space is quoted."""
    return '"%s"' % path if any(c.isspace() for c in path) else path


class HuskJob(QtCore.QObject):
    """One husk: frame N renders `frames[N-1]`, an (asset_id, png_path) pair."""

    progressed = QtCore.Signal(int, int)    # (percent, 100) as husk reports it
    frameDone = QtCore.Signal(int)    # a 1-based frame whose EXR is in place
    finished = QtCore.Signal(str)    # "done", "cancelled" or "failed: <why>"

    def __init__(self, batch: dict, job_dir: str, frames: list) -> None:
        super().__init__()
        self.batch = batch
        self.renderer = batch["renderer"]
        self.job_dir = job_dir
        self.frames = list(frames)
        self.status = ""
        self._proc = None
        self._lines = queue.Queue()
        self._tail = collections.deque(maxlen=30)
        self._done = set()    # the frames the post-frame script reported done
        self._timer = None
        self._cancelled = False

    def exr(self, frame: int) -> str:
        return os.path.join(self.job_dir, "f%d.exr" % frame)

    def command(self) -> list:
        """husk's arguments: the frames, both scripts, progress lines, the stage."""
        prefr = os.path.join(self.job_dir, "preframe.py")
        postfr = os.path.join(self.job_dir, "postframe.py")
        cmd = [os.path.join(hou.getenv("HFS"), "bin", "husk"), "-V", "1a",
               "-R", DELEGATES[self.renderer],
               "--purpose", "geometry,render", "--complexity", "veryhigh",    # the ROP's own
               "-f", "1", "-n", str(len(self.frames)),
               "--preframe-script", _script_arg(prefr),
               "--postframe-script", _script_arg(postfr),
               "-o", os.path.join(self.job_dir, "frame.$F4.exr")]
        restart = RESTART_EVERY.get(self.renderer)
        if restart:
            cmd += ["--restart-delegate", str(restart)]
        return cmd + [self.batch["usd"]]

    def environment(self) -> dict:
        """Houdini's own, the renderer plugins this render does not use excluded."""
        env = dict(os.environ)
        pattern = plugin_exclusion(self.renderer, env.get(EXCLUDE, ""))
        if pattern:
            env[EXCLUDE] = pattern
        return env

    def _write_scripts(self) -> None:
        with open(os.path.join(self.job_dir, "preframe.py"), "w", encoding="utf-8",
                  newline="\n") as fh:    # husk reads Python source as UTF-8, and a prim or a path may not be ASCII
            fh.write(PREFRAME % {"prims": self.batch["prims"], "ball": self.batch["ball"]})
        with open(os.path.join(self.job_dir, "postframe.py"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(POSTFRAME % {"dir": self.job_dir, "done": DONE})

    def _spawn(self) -> None:
        self._write_scripts()
        self._proc = subprocess.Popen(
            self.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=self.environment(), cwd=self.job_dir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))    # Windows: no console
        debug.event("thumb", "husk started", renderer=self.renderer,
                    frames=len(self.frames), pid=self._proc.pid)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        """The reader thread: every output line onto the queue, then None at the end."""
        for raw in iter(self._proc.stdout.readline, b""):
            self._lines.put(raw.decode(errors="replace").rstrip())
        self._lines.put(None)

    def start(self) -> None:
        """In the background: the main thread drains the reader's lines on a timer."""
        self._spawn()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(100)

    def run_blocking(self) -> None:
        """With no event loop (hython, tests): the same lines, handled as they come."""
        self._spawn()
        while True:
            line = self._lines.get()
            if line is None:
                break
            self._handle(line)
        self._finish()

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()    # husk stops within 0.05 s ▸r/husk-startup

    def _drain(self) -> None:
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return
            if line is None:
                self._timer.stop()
                self._finish()
                return
            self._handle(line)

    def _handle(self, line: str) -> None:
        self._tail.append(line)
        if line.startswith(PROGRESS):
            try:
                self.progressed.emit(int(line.split()[1].rstrip("%")), 100)
            except (IndexError, ValueError):
                pass
        elif line.startswith(DONE):
            try:
                frame = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._done.add(frame)
            self.frameDone.emit(frame)

    def _finish(self) -> None:
        """Every frame back is done, whatever the exit: 22.0.482's husk exits 139 after its last."""
        code = self._proc.wait()
        if self._cancelled:
            self.status = "cancelled"
        elif code != 0 and len(self._done) < len(self.frames):
            self.status = "failed: husk exit %d" % code
            debug.event("thumb", "husk failed", renderer=self.renderer, code=code,
                        tail=list(self._tail))
            debug.note("%s thumbnail render stopped (husk exit %d) - the tiles it did not "
                       "finish keep their old picture" % (self.renderer, code))
        else:
            self.status = "done"
        debug.event("thumb", "husk finished", renderer=self.renderer, status=self.status,
                    code=code)
        self.finished.emit(self.status)

    def discard(self) -> None:
        shutil.rmtree(self.job_dir, ignore_errors=True)

    def stop(self, timeout: float = 5.0) -> None:
        """Cancel, wait for husk to exit, then discard: for quitting, where nothing drains."""
        self.cancel()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:    # its files may still be open: the folder stays
                debug.event("thumb", "husk outlived its stop", pid=self._proc.pid)
        self.discard()


class Jobs(QtCore.QObject):
    """The one queue of thumbnail husks, run one at a time."""

    activeChanged = QtCore.Signal(bool)
    progressed = QtCore.Signal(int, int)
    thumbnailWritten = QtCore.Signal(str)    # the asset id whose PNG was just written

    def __init__(self) -> None:
        super().__init__()
        self._waiting = []
        self._running = None

    def busy(self) -> bool:
        return self._running is not None or bool(self._waiting)

    def submit(self, job: HuskJob, blocking: bool = False) -> None:
        """Run `job` after any before it; `blocking` runs it here and now (no event loop)."""
        job.progressed.connect(self.progressed)
        job.frameDone.connect(lambda frame, job=job: self._frame_done(job, frame))
        if blocking:
            self.activeChanged.emit(True)
            try:
                job.run_blocking()
            finally:
                job.discard()
                self.activeChanged.emit(self.busy())
            return
        job.finished.connect(lambda status, job=job: self._job_finished(job))
        self._waiting.append(job)
        if self._running is None:
            self._next()

    def cancel(self) -> None:
        """Stop the running husk and drop the waiting ones; finished thumbnails stay."""
        waiting, self._waiting = self._waiting, []
        for job in waiting:
            job.discard()
        if self._running is not None:
            self._running.cancel()

    def _next(self) -> None:
        if not self._waiting:
            self._running = None
            self.activeChanged.emit(False)
            return
        self._running = self._waiting.pop(0)
        self.activeChanged.emit(True)
        try:
            self._running.start()
        except OSError as exc:    # no husk to start: say so, and go on to the next
            debug.event("thumb", "husk did not start", error=str(exc))
            debug.note("thumbnail render did not start: %s" % exc)
            self._running.discard()
            self._next()

    def _frame_done(self, job: HuskJob, frame: int) -> None:
        if not 1 <= frame <= len(job.frames):
            return
        asset_id, png = job.frames[frame - 1]
        exr = job.exr(frame)
        from amaze import preview
        if os.path.exists(exr) and preview.exr_to_png(exr, png, job.batch["ocio"], asset_id):
            self.thumbnailWritten.emit(asset_id)
        else:    # the tile keeps its old picture: this line is the only trace
            debug.event("thumb", "frame done without a picture", asset_id=asset_id,
                        frame=frame, exr_found=os.path.exists(exr), renderer=job.renderer)
        try:
            os.remove(exr)
        except OSError:
            pass

    def _job_finished(self, job: HuskJob) -> None:
        job.discard()
        if job is self._running:
            self._next()

    def stop_now(self) -> None:
        """At Houdini's exit: no husk outlives the session, and no job leaves its folder."""
        waiting, self._waiting = self._waiting, []
        for job in waiting:
            job.discard()
        if self._running is not None:
            self._running.stop()


jobs = Jobs()
atexit.register(jobs.stop_now)
