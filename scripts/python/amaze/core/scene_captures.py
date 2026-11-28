"""Scene View screenshots as tile thumbnails, and which scene is open. ▸r/tile-captures"""

import os
import time

import hou

from amaze import messages
from amaze.core import captures
from amaze.core import debug, guard, library_db, material
from amaze.helpers import hostos

MAX_THUMB_EDGE = 1024  # the captured image's long edge, in pixels


def _key(path: str) -> str:
    """canonical_path_key, but an empty path stays empty, never the `.` normpath gives it."""
    return hostos.canonical_path_key(path) if path else ""


NON_COMMERCIAL = ("Apprentice", "ApprenticeHD", "Education")    # licences that write .hipnc


def scene_extension() -> str:
    """The scene extension this licence writes; Houdini's save writes any name given ▸r/scene-extension"""
    category = hou.licenseCategory().name()
    if category == "Indie":
        return ".hiplc"
    if category in NON_COMMERCIAL:
        return ".hipnc"
    return ".hip"


def current_scene_path() -> str:
    """What Houdini currently has open, canonicalised."""
    try:
        return _key(hou.hipFile.path() or "")
    except Exception:                                    # noqa: BLE001
        return ""


FAST_DELEGATES = ("houdini gl", "houdini vk")  # delegates that draw the viewport, lowercased


def delegate_is_fast(name) -> bool:
    """Whether a capture through this Hydra delegate is cheap."""
    return str(name or "").strip().lower() in FAST_DELEGATES


def scene_viewer():
    """The scene view under the cursor, else the visible one, else any, else None. GUI only."""
    try:
        import hou
        tab = hou.ui.paneTabUnderCursor()
        if tab is not None and tab.type() == hou.paneTabType.SceneViewer:
            return tab
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import toolutils
        viewer = toolutils.sceneViewer(can_switch_tabs=False)  # raises hou.NotAvailable when no scene viewer is current
        if viewer is not None:
            return viewer
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import hou
        return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    except Exception:                                    # noqa: BLE001
        return None


def viewer_context(viewer) -> str:
    """The network category the Scene View shows, lowercased; for logs only, never to refuse a capture."""
    try:
        pwd = viewer.pwd()
        category = pwd.childTypeCategory() if pwd else None
        return category.name().lower() if category else ""
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "could not read the viewer context",  # logged so a failed read differs from a non-3D context
                    error="%s: %s" % (type(exc).__name__, exc))
        return ""


def viewport_state(viewer=None) -> dict:
    """The scene view's renderer state; read it before a capture, which renders. ▸r/tile-captures"""
    state = {
        "renderer": "",
        "blocking": False,
        "paused": None,
        "readable": False,
    }
    try:
        if viewer is None:
            viewer = scene_viewer()
    except Exception as exc:                             # noqa: BLE001
        state["error"] = "no scene viewer: %s" % exc
        return state
    if viewer is None:
        state["error"] = "no scene viewer"
        return state
    try:
        state["renderer"] = str(viewer.currentHydraRenderer())
        state["readable"] = True
    except Exception as exc:                             # noqa: BLE001
        state["error"] = str(exc)  # an OBJ viewport raises here; that is not blocking
    state["blocking"] = (
        state["readable"] and not delegate_is_fast(state["renderer"]))
    try:
        state["paused"] = bool(viewer.isRendererPaused())
    except Exception:                                    # noqa: BLE001
        state["paused"] = None
    return state



class CaptureRefused(Exception):
    """The capture did not happen; the message is the reason."""


def _looks_blank(png_path: str) -> bool:
    """True when a 16 x 16 sample of the image finds one colour only, or it will not load."""
    try:
        from PySide6 import QtGui
        image = QtGui.QImage(png_path)
        if image.isNull() or image.width() < 2 or image.height() < 2:
            return True
        seen = set()
        step_x = max(1, image.width() // 16)
        step_y = max(1, image.height() // 16)
        for x in range(0, image.width(), step_x):
            for y in range(0, image.height(), step_y):
                seen.add(image.pixel(x, y))
                if len(seen) > 1:
                    return False
        return True
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "blank check failed", error=str(exc))
        return False


def capture_viewport(out: str, viewer=None, user: str = "") -> str:
    """Save a Scene View screenshot to the PNG `out`, put whole; raises CaptureRefused."""
    if not out:
        raise CaptureRefused(messages.CAPTURE_NO_FILE)
    try:
        from husd import assetutils
    except ImportError as exc:
        raise CaptureRefused(messages.CAPTURE_NO_ASSETUTILS % exc)
    viewer = viewer or scene_viewer()    # pass the one _viewer_for_capture checked ▸r/tile-captures
    if viewer is None:
        raise CaptureRefused(messages.CAPTURE_NO_VIEWER)
    try:
        width, height = viewer.curViewport().resolutionInPixels()
    except Exception as exc:                             # noqa: BLE001
        raise CaptureRefused(messages.CAPTURE_VIEWPORT_UNMEASURED % exc)
    if not width or not height:
        raise CaptureRefused(messages.CAPTURE_VIEWPORT_ZERO)
    longest = max(width, height)
    if longest > MAX_THUMB_EDGE:
        scale = MAX_THUMB_EDGE / float(longest)
        width, height = int(width * scale), int(height * scale)

    renderer = "unknown"  # logged before the call, so a capture that blocks still leaves a record
    try:
        renderer = str(viewer.currentHydraRenderer())
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "could not read the viewport renderer",
                    error=str(exc))
    debug.event("hip", "capture starting", file=out,
                renderer=renderer, res=(width, height))
    started = time.time()
    folder = os.path.dirname(out)
    try:
        material.make_folders(out)    # a snippet's or color's first file makes its folder
    except OSError as exc:
        raise CaptureRefused(messages.CAPTURE_FOLDER_FAILED % (folder, exc))

    def write(scratch):
        try:
            assetutils.saveThumbnailFromViewer(
                sceneviewer=viewer, output=scratch, croptocamera=False, res=(width, height))
        except Exception as exc:                         # noqa: BLE001
            raise CaptureRefused(messages.CAPTURE_WRITE_FAILED % (type(exc).__name__, exc))
        if not os.path.isfile(scratch):
            _log_nothing_written(viewer, scratch, out)
            raise CaptureRefused(messages.CAPTURE_WROTE_NOTHING)
        if _looks_blank(scratch):
            raise CaptureRefused(messages.CAPTURE_FLAT)

    if not guard.put_rendered(out, write, user):
        raise CaptureRefused(messages.CAPTURE_NOT_STORED)
    debug.event("hip", "thumbnail captured", png=out,
                res=(width, height), renderer=renderer,
                seconds=round(time.time() - started, 2))
    return out


def _log_nothing_written(viewer, scratch: str, out: str) -> None:
    """Everything cheap to log when Houdini says it captured but wrote no file."""
    folder = os.path.dirname(out)
    detail = {"scratch": scratch, "context": viewer_context(viewer)}
    try:
        detail["frame"] = hou.frame()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        detail["viewport"] = viewer.curViewport().name()
        detail["camera"] = str(viewer.curViewport().camera())
    except Exception as exc:                             # noqa: BLE001
        detail["viewport_error"] = "%s: %s" % (type(exc).__name__, exc)
    try:
        detail["dir_writable"] = os.access(folder, os.W_OK)
        siblings = [n for n in os.listdir(folder)
                    if n.startswith(os.path.basename(out)[:12])]
        detail["siblings"] = siblings[:4]
    except OSError as exc:
        detail["dir_error"] = str(exc)
    debug.event("hip", "capture wrote nothing", **detail)


def capture_open_scene(preferences, target: str = "") -> str:
    """Capture the open scene for its File tile, all scene checks here; `target` must be it."""
    opened = current_scene_path()
    if not target:
        if not opened:
            raise CaptureRefused(messages.CAPTURE_NO_SCENE)
        target = opened
    elif target != opened:
        debug.event("hip", "capture not taken - a different scene is open",
                    wanted=target, open=opened)
        raise CaptureRefused(messages.CAPTURE_OTHER_SCENE)

    if not os.path.isfile(target):  # an unsaved scene has no file to file a thumbnail against
        debug.event("hip", "capture not taken - the scene is not on disk",
                    file=target)
        raise CaptureRefused(messages.CAPTURE_SCENE_UNSAVED)

    key = captures.file_key(preferences, target)
    return capture_tile(captures.file_path(preferences, key), key,
                        library_db.user(preferences))


def capture_tile(out: str, key: str, user: str = "") -> str:
    """Capture the Scene View as the thumbnail of tile `key`, by `user`, then signal every model."""
    path = capture_viewport(out, _viewer_for_capture(), user)
    captures.signal_capture_saved(key)    # the engine serves a decoded copy until the model drops it
    return path


def _viewer_for_capture():
    """The Scene View to capture, checked BEFORE asking it for a frame: every capture renders."""
    viewer = scene_viewer()
    state = viewport_state(viewer)
    if state.get("blocking"):
        debug.event("hip", "capture not taken - viewport is rendering",
                    renderer=state.get("renderer", ""),
                    error=state.get("error", ""))
        message = messages.CAPTURE_VIEWPORT_RENDERING
        if debug.is_on():    # Debug Mode only: the renderer's name is for diagnosing
            message += messages.CAPTURE_RENDERER_DETECTED % (state.get("renderer") or "unreadable")
        raise CaptureRefused(message)
    return viewer


