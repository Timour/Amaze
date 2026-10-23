"""Photographing the Scene View as a tile's picture, and which scene is open. ▸r/tile-captures"""

import os
import time

import hou

from amaze.core import captures
from amaze.core import debug
from amaze.helpers import hostos

MAX_THUMB_EDGE = 1024  # the captured image's long edge - a 4K viewport would otherwise write a multi-megabyte PNG per scene, and these are tiles


def _key(path: str) -> str:
    """canonical_path_key, but "" stays "" - normpath("") is ".", a TRUTHY key equal to current_scene_path() when nothing is open, which failed OPEN the one check that prevents mis-filing."""
    return hostos.canonical_path_key(path) if path else ""


def current_scene_path() -> str:
    """What Houdini currently has open, canonicalised."""
    try:
        return _key(hou.hipFile.path() or "")
    except Exception:                                    # noqa: BLE001
        return ""


FAST_DELEGATES = ("houdini gl", "houdini vk")  # delegates that DRAW the viewport rather than render it - a capture through one costs a raster frame; 22.0.394 reports "Houdini VK", older builds "Houdini GL"


def delegate_is_fast(name) -> bool:
    """Whether a capture through this Hydra delegate is cheap."""
    return str(name or "").strip().lower() in FAST_DELEGATES


def scene_viewer():
    """The scene view the user is actually looking at, or None - in order: under the cursor, then the stock helper with can_switch_tabs=False (its shipped source filters to a VISIBLE viewer, and merely asking must not rearrange panes), then any viewer at all; `paneTabOfType` is plain indexing that can hand back a hidden tab, so preferring it was a regression. GUI only."""
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
    """The network category the Scene View is showing, lowercased - DIAGNOSTIC ONLY: the network being browsed does NOT determine whether the viewport can be photographed (a copnet still shows a real 3D viewport, and a refusal inferred from a log line once blocked legitimate work)."""
    try:
        pwd = viewer.pwd()
        category = pwd.childTypeCategory() if pwd else None
        return category.name().lower() if category else ""
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "could not read the viewer context",  # say WHY: "not a 3D context" and "we could not ask" must not look the same
                    error="%s: %s" % (type(exc).__name__, exc))
        return ""


def viewport_state(viewer=None) -> dict:
    """What the scene view is doing BEFORE asking it for a frame - every image-producing route Houdini offers RENDERS (no call copies the displayed frame; QWidget.grab() on the Vulkan surface hangs), so with a pathtracer a capture blocks unboundedly, and reading the state first turns that surprise into a choice."""
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
        state["error"] = str(exc)  # an OBJ viewport is not Hydra-based, so this raises there - the ordinary case; only stand in the way of a delegate POSITIVELY recognised as a renderer
    state["blocking"] = (
        state["readable"] and not delegate_is_fast(state["renderer"]))
    try:
        state["paused"] = bool(viewer.isRendererPaused())
    except Exception:                                    # noqa: BLE001
        state["paused"] = None
    return state



class CaptureRefused(Exception):
    """The capture did not happen, WITH the reason - never a bare False: a missing thumbnail and a failed capture must not look the same to a caller."""


def _looks_blank(png_path: str) -> bool:
    """True when the image carries no picture worth keeping - a capture taken before the viewport drew is a single flat colour, and storing it hides the scene behind a grey square forever. BLANK MEANS ONE COLOUR (a more-than-two threshold refused real frames: Houdini's default scheme is flat black, so a wireframe view samples exactly two), sampled not scanned, and deliberately weak the other way - a gradient background already samples many colours, so the flat case is all this can honestly catch."""
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
        if viewer is None:  # resolved by the CALLER when there is one: resolving again here let the guard clear on the GL viewport and the flipbook run on the Karma one, because rung one is "under the cursor" and the mouse moved between the calls
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

    renderer = "unknown"  # WHICH delegate and HOW LONG, recorded BEFORE the call: a record written only on completion cannot distinguish "the user clicked late" from "the capture blocked"
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
        detail = {"scratch": scratch, "context": viewer_context(viewer)}  # WHY, not just THAT: this fired from a Copernicus session naming only the missing path, which sent the diagnosis down a wrong road - record everything cheap that could tell the causes apart
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
    _discard(out + ".prev")  # sweep orphans of earlier scratch schemes (.prev from move-aside, .png.new from the extension-breaking one, the FIXED .capturing name) so an upgrading machine does not keep one forever
    _discard(out + ".new")
    _discard(_legacy_capture_scratch(out))
    debug.event("hip", "thumbnail captured", png=out,
                res=(width, height), renderer=renderer,
                seconds=round(time.time() - started, 2))
    return out


def _capture_scratch(out: str) -> str:
    """The name Houdini writes a capture to before it is put in place - three rules, each got wrong once, a function so a headless test can pin them: write ASIDE and replace (never move the live thumbnail first), the suffix goes BEFORE the extension (Houdini picks the format from it - ▸r/image-extension), and the name must be UNIQUE (▸r/atomic-writes). `create=False`, so `not os.path.isfile(scratch)` keeps meaning that Houdini wrote nothing."""
    return hostos.render_scratch(out, "capturing")


def _legacy_capture_scratch(out: str) -> str:
    """The FIXED name this used before the unique one, so an upgrading machine can be swept clean of the single leftover a mid-capture death left - nothing else would ever come back for it."""
    root, ext = os.path.splitext(out)
    return root + ".capturing" + (ext or ".png")


def _discard(path: str) -> None:
    """Remove a scratch file, saying why if it will not go - with the write-aside shape there is nothing to restore, because the live thumbnail is never moved."""
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
        debug.event("hip", "capture refused - a different scene is open",  # say what is TRUE: the old wording claimed the viewport showed a different scene even when it showed exactly this one and Amaze simply had not opened it
                    wanted=target, open=opened)
        raise CaptureRefused(
            "Houdini has a different scene open, so the capture would "
            "be filed under the wrong name.\n\n"
            "Open this scene first.")

    if not os.path.isfile(target):  # an unsaved scene has a path that does not exist - capturing it wrote a PNG no tile can show, and the cwd-derived path made every later unsaved session overwrite the same slot
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


