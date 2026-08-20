"""The scene-capture store and open-scene state for hip files: the capture store and its manifest, the capture decision path, the placeholder, `matched_extension`, and which scene is open or was opened by Amaze. Two rules, both unlike every other section: thumbnails are CAPTURED, never rendered (a scene cannot be imported into a scene Amaze controls - it IS one - so a row with no capture has no thumbnail and nothing renders in the background), and the store is NOT mtime-invalidated (dropping a hand-framed capture because the scene re-saved would erase what the user composed). Captures live in their own directory, path -> sha1 -> png plus a manifest - treat that layout as a contract, an external reader consumes it."""

import hashlib
import json
import os
import shutil
import time

import hou
from PySide6 import QtCore

from amaze.core import debug
from amaze.helpers import hostos, ui_helpers

HIP_EXTENSIONS = (".hiplc", ".hipnc", ".hip")  # every Houdini scene extension is ONE file type - a mixed library must not sort them into different sections or show one and hide the other

MAX_THUMB_EDGE = 1024  # the captured image's long edge - a 4K viewport would otherwise write a multi-megabyte PNG per scene, and these are tiles


def matched_extension(name: str) -> str:
    """The HIP_EXTENSIONS entry the filename ends with, or ''."""
    return hostos.matched_extension(name, HIP_EXTENSIONS)



_thumb_dir_memo: dict = globals().get("_thumb_dir_memo", {})  # the resolved capture directory, memoised per session: thumb_dir() runs a MIGRATION (makedirs, isdirs, possibly a listdir+rename per entry) and thumb_path() reaches it from every DecorationRole paint - measured, 10 calls cost 20 makedirs and 40 isdir before the memo


def forget_thumb_dir() -> None:
    """Drop the memo - the cache or config root has moved."""
    _thumb_dir_memo.clear()


def thumb_dir() -> str:
    """Where captured scene views live: under config_root, NOT the cache - a hand-framed capture cannot be regenerated, and the cache root is what the OS, a preference and Delete Local Cache are all entitled to purge; migrates the old cache-root folder in on first use by rename, newer captures winning a per-file collision."""
    key = (hostos.config_root, hostos.cache_root, hostos.cache_generation())  # a key that costs NOTHING to build: the two resolver FUNCTIONS by identity (the suite replaces them wholesale, and a memo surviving that hands one test's directory to the next) plus cache_generation(), which set_cache_override bumps; keying on resolved roots paid two makedirs per ask
    if _thumb_dir_memo.get("key") == key:
        resolved = _thumb_dir_memo.get("dir")
        if resolved:
            return resolved
    home = os.path.join(hostos.config_root(), "hip_thumbnails")
    legacy = os.path.join(hostos.cache_root(), "hip_thumbnails")
    if not os.path.isdir(home):
        if os.path.isdir(legacy):
            try:
                os.makedirs(os.path.dirname(home), exist_ok=True)
                os.rename(legacy, home)
                debug.event("hip", "captures moved out of the cache",
                            src=legacy, dest=home)
            except OSError:
                try:  # cross-volume or held - copy the slow way, keep going
                    shutil.copytree(legacy, home, dirs_exist_ok=True)
                    debug.event("hip", "captures copied out of the cache",
                                src=legacy, dest=home)
                except OSError as exc:
                    debug.event("hip", "captures NOT migrated - still in "
                                "the cache", error=str(exc))
                    _thumb_dir_memo.update(dir=legacy, key=key)
                    return legacy
        else:
            try:
                os.makedirs(home, exist_ok=True)
            except OSError:
                _thumb_dir_memo.update(dir=legacy, key=key)
                return legacy
    elif os.path.isdir(legacy):
        for name in os.listdir(legacy):  # both exist: an interrupted earlier migration - adopt what the old folder holds without overwriting newer captures
            target = os.path.join(home, name)
            if not os.path.exists(target):
                try:
                    os.rename(os.path.join(legacy, name), target)
                except OSError:
                    pass
        try:
            os.rmdir(legacy)               # only succeeds when emptied
        except OSError:
            pass
    _thumb_dir_memo.update(dir=home, key=key)
    return home


def thumb_path(hip_path: str) -> str:
    """The PNG slot for a scene file - sha1(canonical path).png, the same scheme the other file-based caches use and one an external consumer can reproduce without reading our code."""
    key = hostos.canonical_path_key(hip_path or "")
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(thumb_dir(), digest + ".png")


def has_thumbnail(hip_path: str) -> bool:
    """Whether a non-empty capture exists for this scene - the tests pin the store's contract through it (a zero-byte file is no thumbnail, and a re-saved scene must not lose one), which is its reason to stay."""
    path = thumb_path(hip_path)
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _manifest_path() -> str:
    return os.path.join(thumb_dir(), "manifest.json")


def _record_manifest(hip_path: str, png: str) -> None:
    """Remember which scene a hash belongs to - without this the directory of one-way hashes is unreadable by a human; written whole and small, and a manifest that will not parse is REPLACED rather than merged, because losing the map is recoverable (re-capture) while refusing to record anything is not."""
    data = {}
    path = _manifest_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, ValueError) as exc:
        debug.event("hip", "manifest unreadable - starting a new one",
                    error=str(exc), path=path)
    data[hostos.canonical_path_key(hip_path)] = {
        "thumbnail": os.path.basename(png),
    }
    try:
        os.makedirs(thumb_dir(), exist_ok=True)
        hostos.write_json_atomic(path, data, indent=2)  # ATOMIC like every other durable JSON store here - the one writer still opening "w" left a truncated file on a mid-dump death, which the next capture read as unreadable and replaced with a one-entry map
    except OSError as exc:
        debug.event("hip", "manifest not written", error=str(exc))




def placeholder_image():
    """The tile shown for a scene with no capture yet - not a loading state that resolves on its own but the RESTING state until someone presses Capture, so it has to look deliberate; the render and its cache are `ui_helpers.svg_image`, and this stays because which SVG stands for an uncaptured scene is this section's concept."""
    return ui_helpers.svg_image("icon_hip.svg")



_state = globals().get("_state", {"opened": ""})  # survives importlib.reload - the panel reloads modules in place, and a plain assignment would forget which scene Amaze opened


def _key(path: str) -> str:
    """canonical_path_key, but "" stays "" - normpath("") is ".", a TRUTHY key equal to current_scene_path() when nothing is open, which failed OPEN the one check that prevents mis-filing."""
    return hostos.canonical_path_key(path) if path else ""


def note_opened(path: str) -> None:
    """Remember that Amaze opened this scene."""
    _state["opened"] = _key(path or "")


def opened_path() -> str:
    return _state.get("opened", "")


def current_scene_path() -> str:
    """What Houdini currently has open, canonicalised."""
    try:
        return _key(hou.hipFile.path() or "")
    except Exception:                                    # noqa: BLE001
        return ""


def amaze_opened_current_scene() -> bool:
    """Whether the scene on screen is the one Amaze opened - compares the RECORDED path against what is actually open, so a File > Open or a crash recovery simply stops matching with nothing to get out of sync; the capture policy deliberately dropped this clause (two source-derived tests pin that it stays dropped), and the behaviour tests keep the fail-closed semantics honest, which is its reason to stay."""
    opened = opened_path()
    return bool(opened) and opened == current_scene_path()



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


def capture_thumbnail(hip_path: str, viewer=None) -> str:
    """Capture the CURRENT scene view as this scene's thumbnail and return the PNG path; raises CaptureRefused with a readable reason. Uses `husd.assetutils.saveThumbnailFromViewer` (identical in 21.0.790 and 22.0.394) with croptocamera=False - cropping scales into the requested resolution, so any camera-aperture mismatch distorts, while the whole viewport at native aspect needs no camera at all - and res = the viewport's own pixels, capped. GUI ONLY: there is no viewport headless."""
    if not hip_path:
        raise CaptureRefused("No scene file was given.")
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
    debug.event("hip", "capture starting", file=hip_path,
                renderer=renderer, res=(width, height))
    started = time.time()

    out = thumb_path(hip_path)
    try:
        os.makedirs(thumb_dir(), exist_ok=True)
    except OSError as exc:
        raise CaptureRefused("Could not create %s: %s" % (thumb_dir(), exc))
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
            detail["dir_writable"] = os.access(thumb_dir(), os.W_OK)
            siblings = [n for n in os.listdir(thumb_dir())
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
    _record_manifest(hip_path, out)
    debug.event("hip", "thumbnail captured", file=hip_path, png=out,
                res=(width, height), renderer=renderer,
                seconds=round(time.time() - started, 2))
    try:
        signals.captured.emit(hip_path)  # tell every live model the file changed - the engine serves a decoded copy from memory, and without this the capture succeeds while the tile keeps the old picture
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "could not announce the capture",
                    error=str(exc), file=hip_path)
    return out


def _capture_scratch(out: str) -> str:
    """The name Houdini writes a capture to before it is put in place - three rules, each got wrong once, a function so a headless test can pin them: write ASIDE and replace (never move the live thumbnail first), the suffix goes BEFORE the extension (Houdini picks the format from it - ▸r/image-extension), and the name must be UNIQUE (▸r/atomic-writes). `create=False`, so `not os.path.isfile(scratch)` keeps meaning that Houdini wrote nothing."""
    root, ext = os.path.splitext(out)
    return hostos.unique_scratch(out, suffix=".capturing" + (ext or ".png"),
                                 create=False)


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


def capture_open_scene(target: str = "") -> str:
    """Capture the open scene as its thumbnail - THE decision path, every refusal this feature can make in one place so the panel button and the shelf tool cannot drift; raises CaptureRefused and never touches hou.ui, which keeps it headlessly testable. `target` empty (the shelf tool) means whatever is open; given (the tile menu) it must MATCH what is open, or the capture files under the wrong name."""
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

    viewer = scene_viewer()  # look at the viewport BEFORE asking it for a frame - every route renders, so a pathtracing delegate blocks for as long as that render takes

    state = viewport_state(viewer)
    if state.get("blocking"):
        debug.event("hip", "capture refused - viewport is rendering",
                    renderer=state.get("renderer", ""),
                    error=state.get("error", ""))
        message = "Please stop the viewport render before capturing."
        if debug.is_on():
            message += "\n\nDetected: %s" % (  # Debug Mode only: in normal use naming the renderer tells the user what they chose; when diagnosing, it is the whole point
                state.get("renderer") or "unreadable")
        raise CaptureRefused(message)
    return capture_thumbnail(target, viewer)


class _HipSignals(QtCore.QObject):
    """Relay announcing a landed capture, so a capture from ANYWHERE repaints the tile - the refresh is the CAPTURE's business, not the button's, which is the shape that broke the moment a second caller (the shelf tool) existed."""

    captured = QtCore.Signal(object)     # the scene path, replaced


_RELAY_VERSION = 1  # bumped whenever a signal is ADDED, REMOVED or changes arity: `hasattr` only proves a name present, and an old-arity relay left in place makes connect() succeed and the emit raise a swallowed TypeError - every tile silently stops repainting

signals = globals().get("signals")  # reload-stable, the documented idiom: a module-level object rebuilt by importlib.reload would strand every connection made by the previous load
if signals is None or getattr(signals, "version", None) != _RELAY_VERSION:
    signals = _HipSignals()
    signals.version = _RELAY_VERSION


