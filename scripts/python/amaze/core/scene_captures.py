"""Photographing the Scene View as a tile's picture, and which scene is open. ▸r/tile-captures"""

import os
import time

import hou

from amaze.core import captures
from amaze.core import debug
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
        debug.event("hip", "could not read the viewer context",  # say WHY: "not a 3D context" and "we could not ask" must not look the same
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


def capture_viewport(out: str, viewer=None) -> str:
    """Photograph the Scene View into the PNG `out`; raises CaptureRefused. ▸r/tile-captures"""
    if not out:
        raise CaptureRefused("No file was given for the capture.")
    try:
        import toolutils
        from husd import assetutils
    except ImportError as exc:
        raise CaptureRefused(
            "This Houdini has no husd.assetutils (%s), so the viewport "
            "cannot be captured." % exc)
    try:
        if viewer is None:  # pass the viewer the guard checked, or the capture may use another
            viewer = scene_viewer()
    except Exception as exc:                             # noqa: BLE001
        raise CaptureRefused(
            "No scene viewer is available (%s). A capture needs a "
            "visible viewport." % exc)
    if viewer is None:
        raise CaptureRefused(
            "No scene viewer is open - the capture needs a visible "
            "viewport to photograph.")
    try:
        width, height = viewer.curViewport().resolutionInPixels()
    except Exception as exc:                             # noqa: BLE001
        raise CaptureRefused("Could not measure the viewport: %s" % exc)
    if not width or not height:
        raise CaptureRefused(
            "The viewport reports a zero size - it may be hidden or "
            "collapsed.")
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
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise CaptureRefused("Could not create %s: %s" % (folder, exc))
    scratch = _capture_scratch(out)
    try:
        assetutils.saveThumbnailFromViewer(
            sceneviewer=viewer, output=scratch, croptocamera=False,
            res=(width, height),
        )
    except Exception as exc:                             # noqa: BLE001
        _discard(scratch)
        raise CaptureRefused(
            "Houdini could not write the thumbnail: %s: %s"
            % (type(exc).__name__, exc))
    if not os.path.isfile(scratch):
        detail = {"scratch": scratch, "context": viewer_context(viewer)}  # everything cheap to log
        try:
            detail["frame"] = hou.frame()
        except Exception:                                # noqa: BLE001
            pass
        try:
            detail["viewport"] = viewer.curViewport().name()
            detail["camera"] = str(viewer.curViewport().camera())
        except Exception as exc:                         # noqa: BLE001
            detail["viewport_error"] = "%s: %s" % (type(exc).__name__, exc)
        try:
            detail["dir_writable"] = os.access(folder, os.W_OK)
            siblings = [n for n in os.listdir(folder)
                        if n.startswith(os.path.basename(out)[:12])]
            detail["siblings"] = siblings[:4]
        except OSError as exc:
            detail["dir_error"] = str(exc)
        debug.event("hip", "capture wrote nothing", **detail)
        raise CaptureRefused(
            "Houdini reported the capture finished but no image was "
            "written.\n\nNothing was changed. The debug log has the "
            "viewport details - Preferences > Save Log... if you want "
            "to send them on.")
    if _looks_blank(scratch):
        _discard(scratch)
        raise CaptureRefused(
            "The captured frame was a single flat colour, so nothing was "
            "stored. The existing thumbnail is untouched.")
    try:
        os.replace(scratch, out)
    except OSError as exc:
        _discard(scratch)
        raise CaptureRefused(
            "The thumbnail could not be put in place: %s" % exc)
    _discard(out + ".prev")  # sweeps the scratch names older versions left behind
    _discard(out + ".new")
    _discard(_legacy_capture_scratch(out))
    debug.event("hip", "thumbnail captured", png=out,
                res=(width, height), renderer=renderer,
                seconds=round(time.time() - started, 2))
    return out


def _capture_scratch(out: str) -> str:
    """A unique scratch name beside `out`, the suffix before the extension. ▸r/image-extension"""
    return hostos.render_scratch(out, "capturing")


def _legacy_capture_scratch(out: str) -> str:
    """The fixed scratch name older versions used, for sweeping."""
    root, ext = os.path.splitext(out)
    return root + ".capturing" + (ext or ".png")


def _discard(path: str) -> None:
    """Remove a scratch file, logging why if it will not go."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        debug.event("hip", "could not remove a scratch thumbnail",
                    error=str(exc), path=path)


def capture_open_scene(preferences, target: str = "") -> str:
    """The open scene onto its File tile, every refusal in one place; `target` must be it."""
    opened = current_scene_path()
    if not target:
        if not opened:
            raise CaptureRefused(
                "No scene is open, so there is nothing to capture.")
        target = opened
    elif target != opened:
        debug.event("hip", "capture refused - a different scene is open",
                    wanted=target, open=opened)
        raise CaptureRefused(
            "Houdini has a different scene open, so the capture would "
            "be filed under the wrong name.\n\n"
            "Open this scene first.")

    if not os.path.isfile(target):  # an unsaved scene has no file to file a thumbnail against
        debug.event("hip", "capture refused - the scene is not on disk",
                    file=target)
        raise CaptureRefused(
            "This scene has not been saved yet, so there is nothing to "
            "file a thumbnail against.\n\nSave the scene first.")

    key = captures.file_key(preferences, target)
    return capture_tile(captures.file_path(preferences, key), key)


def capture_tile(out: str, key: str) -> str:
    """Photograph the Scene View as the picture of the tile keyed `key`, then tell every model."""
    path = capture_viewport(out, _viewer_for_capture())
    captures.announce(key)    # the engine serves a decoded copy until the model drops it
    return path


def _viewer_for_capture():
    """The Scene View to photograph, read BEFORE asking it for a frame: every route renders."""
    viewer = scene_viewer()
    state = viewport_state(viewer)
    if state.get("blocking"):
        debug.event("hip", "capture refused - viewport is rendering",
                    renderer=state.get("renderer", ""),
                    error=state.get("error", ""))
        message = "Please stop the viewport render before capturing."
        if debug.is_on():    # Debug Mode only: the renderer's name is for diagnosing
            message += "\n\nDetected: %s" % (state.get("renderer") or "unreadable")
        raise CaptureRefused(message)
    return viewer


