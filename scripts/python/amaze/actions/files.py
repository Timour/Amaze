"""What the File models need from Houdini, and their geometry render. ▸archive/actions/files.py"""

import os

import hou
from PySide6 import QtCore, QtGui

from amaze.core import debug, geo_library, scene_captures, thumbnails
from amaze.helpers import helpers, hostos
from amaze.render import thumbs

GEO_PASS_LOG = "geo thumbnails"  # per-item records one pass may write; the budget is per pass
GEO_PASS_FAIL_LOG = "geo thumbnails failed"
GEO_PASS_LOG_BUDGET = 20


def connect(files_model, folders_model, os_icon=None) -> None:
    """Hand the File models $HFS, the open scene, Write Paths As, the geometry render and icons."""
    files_model.hfs = hou.text.expandString("$HFS")
    files_model.open_scene = lambda: scene_captures.current_scene_path()
    files_model.render_geo = lambda misses: render_geo_misses(files_model, misses)
    files_model.os_icon = os_icon
    folders_model.write_path = lambda path, style: helpers.houdini_path(path, style)


def render_geo_misses(model, misses: list) -> None:
    """Render `model`'s missing geometry thumbnails now: blocking, Esc stops it, each lands at once."""
    misses = [pair for pair in misses  # a CACHE file gets no thumbnail unasked
              if not geo_library.is_cache(pair[1])]
    if not misses:
        return
    cache = model._get_geo_cache()
    size = model.preferences.rendersize
    thumber = thumbs.ThumbNailRenderer(model.preferences)
    cache.ensure_dir()
    scratch_seed = os.path.join(cache.cache_dir, "geo_render.png")  # one unique scratch per item
    total = len(misses)
    done = 0
    failed = []
    debug.begin_pass(GEO_PASS_LOG)  # a fresh allowance for this pass's per-item records
    debug.begin_pass(GEO_PASS_FAIL_LOG)
    model.progress_changed.emit(0, total)
    tmp_path = ""    # bound before the try: an interrupt on the first tick reaches the finally
    try:
        with hou.InterruptableOperation(
            "Rendering geometry thumbnails",
            "Rendering geometry thumbnails",
            open_interrupt_dialog=True,
        ) as operation:
            for row, full in misses:
                operation.updateProgress(done / total)
                if debug.pass_budget(GEO_PASS_LOG, GEO_PASS_LOG_BUDGET):
                    debug.event("file", "geo thumbnail",
                                i=done + 1, total=total, file=full)
                ok = False
                tmp_path = hostos.render_scratch(scratch_seed)
                try:
                    ok = thumber.create_thumb_geo_file(
                        full, tmp_path, size)
                except hou.OperationInterrupted:
                    raise
                except Exception as exc:             # noqa: BLE001
                    failed.append(full)
                    if debug.pass_budget(GEO_PASS_FAIL_LOG,
                                         GEO_PASS_LOG_BUDGET):
                        debug.event("file", "geo thumbnail failed",
                                    file=full, error=str(exc))
                pictured = False
                try:
                    if ok:
                        image = QtGui.QImage(tmp_path)
                        if not image.isNull():
                            cache.put(full, image)
                            thumbnails.engine.deposit(
                                ("geo", full, cache.cache_dir), image)
                            pictured = True
                finally:  # gone before the next item, so no later render inherits it
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                if not pictured:
                    operation.updateProgress(done / total)    # an Esc'd render ends imageless too; this raises
                    cache.remember_failure(full)
                done += 1
                model.progress_changed.emit(done, total)
                QtCore.QCoreApplication.processEvents(  # paints only, so no input re-enters the panel
                    QtCore.QEventLoop.ProcessEventsFlag
                    .ExcludeUserInputEvents
                )
    except hou.OperationInterrupted:
        debug.event("file", "geo pass interrupted",
                    done=done, total=total)
    finally:
        debug.event("file", "geo pass done", done=done, total=total,  # one record per pass, always
                    failed=len(failed), files=failed)
        if not model._progress_keys:  # the image batch still owns the bar while it runs
            model.progress_changed.emit(0, 0)
        cache.save()
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
