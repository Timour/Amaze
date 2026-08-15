"""
The scene-capture store and open-scene state for hip files.

The HIP section merged into the File section on 2026-07-31
(core/file_library.py), taking its models with it. What stays here is
everything a hip ROW still needs wherever it appears: the capture
store and its manifest, the capture decision path, the placeholder,
matched_extension, and which scene is open / was opened by Amaze.

TWO THINGS ARE DELIBERATELY DIFFERENT FROM EVERY OTHER SECTION.

**Thumbnails are CAPTURED, never rendered.** Geometry renders a missing
thumbnail on demand: it imports the file into a scene Amaze controls and
frames a camera at it. A scene file cannot be imported into a controlled
scene - it IS a scene - and re-rendering one means reconstructing it,
which fails the moment any dependency is missing. Measured 2026-07-28 on
the first real scene tried: a LOP scene whose sublayer .usdc had been
renamed out from under it could not be cooked at all, headless or
otherwise. So a HIP thumbnail is a capture of the scene view as it was
actually displayed - `husd.assetutils.saveThumbnailFromViewer`, which
wraps a flipbook and therefore keeps handles, gizmos and overlays. A row
with no capture yet simply has no thumbnail; nothing renders in the
background, and opening a folder never blocks.

**The store is not mtime-invalidated.** ThumbnailCache drops an entry
when the source file changes, which is right for a derived render and
wrong for a hand-framed one: re-saving a scene would silently erase a
thumbnail the user deliberately composed. HIP thumbnails live in their
own directory keyed by a hash of the absolute path and persist until
explicitly re-captured. That layout - path -> sha1 -> png, plus a
manifest - is also what an external reader (Anchorpoint, say) would
consume, so it is a deliberate contract rather than an implementation
detail.

BETA: the section is functional but young. Known gaps are listed in
AmazeNotes/devlog.md rather than pretended away here.
"""

import hashlib
import json
import os
import shutil
import time

import hou
from PySide6 import QtCore

from amaze.core import debug
from amaze.helpers import hostos, ui_helpers

#: Every Houdini scene extension is ONE file type. A library that holds
#: a mix - your own .hiplc beside someone else's .hip - must not sort
#: them into different sections or show one and hide the other.
HIP_EXTENSIONS = (".hiplc", ".hipnc", ".hip")

#: The captured image's long edge is capped here. A 4K viewport would
#: otherwise write a multi-megabyte PNG per scene, and these are tiles.
MAX_THUMB_EDGE = 1024


def matched_extension(name: str) -> str:
    """The HIP_EXTENSIONS entry the filename ends with, or ''."""
    return hostos.matched_extension(name, HIP_EXTENSIONS)


# ------------------------------------------------------- thumbnail store

#: The resolved capture directory, memoised for the session.
#:
#: thumb_dir() runs a MIGRATION - config_root() and cache_root() each
#: do an exists + makedirs (a real mkdir syscall), then two isdir
#: checks, then possibly a full listdir and a rename per entry. It is
#: called by thumb_path(), which data() calls on every DecorationRole
#: read, which the delegate performs on every paint: measured, 10
#: thumb_path() calls cost 20 makedirs and 40 isdir. Scrolling a folder
#: of scenes paid that per visible tile per frame, on the main thread,
#: inside paint - while folders.py:81 states the opposite intent for
#: the sidebar ("cached so painting the sidebar never touches the
#: disk"). The interrupted-migration branch is worse: it listdirs the
#: legacy folder on EVERY call, permanently, when one file blocks the
#: rename.
#:
#: A migration is a once-per-session job. Cleared by
#: hostos.set_cache_override, because the tests point the cache
#: elsewhere between cases and a memo that outlived that would hand
#: one test's directory to the next.
_thumb_dir_memo: dict = globals().get("_thumb_dir_memo", {})


def forget_thumb_dir() -> None:
    """Drop the memo - the cache or config root has moved."""
    _thumb_dir_memo.clear()


def thumb_dir() -> str:
    """Where captured scene views live: under config_root, NOT the cache.

    These are hand-framed captures - somebody stood in the viewport and
    chose an angle - and they cannot be regenerated: rebuilding one
    means reconstructing the whole scene, which fails whenever a
    dependency has moved. The cache root is the directory the OS, a
    cache-clear preference and Delete Local Cache are all entitled to
    purge; durable, non-regenerable data was the one thing that must
    not live there (the same rule the corpus baselines follow).

    Migrates the old cache-root folder in on first use, by rename, so
    existing captures survive the location becoming correct. A capture
    already present in the new home wins a per-file collision: it is
    the one more recently written.
    """
    # THE KEY COSTS NOTHING TO BUILD, which is the whole point. Keying
    # it on the resolved roots was the obvious version and still paid
    # two `makedirs(exist_ok=True)` per call just to ask the question -
    # CPython's makedirs calls isdir to decide whether to swallow the
    # FileExistsError, so 20 paints still cost 40 stats. This is three
    # identity comparisons instead:
    #
    #   * the two resolver FUNCTIONS, because the suite redirects them
    #     wholesale (test_support.fixture_panel replaces config_root;
    #     CapturesLiveOutsideTheCacheTest replaces both), and a memo
    #     that survived that hands one test's directory to the next -
    #     which is exactly what a counter-only key did;
    #   * hostos.cache_generation(), which set_cache_override bumps, so
    #     Preferences pointing the cache somewhere new is noticed
    #     without either function being replaced.
    #
    # $AMAZE_CACHE_DIR is read at process start and never changes
    # mid-session, so it needs no term here.
    key = (hostos.config_root, hostos.cache_root, hostos.cache_generation())
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
                # Cross-volume or held - copy the slow way, keep going.
                try:
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
        # Both exist: an interrupted earlier migration. Adopt what the
        # old folder still holds without overwriting newer captures.
        for name in os.listdir(legacy):
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
    """The PNG slot for a scene file.

    Keyed by a hash of the ABSOLUTE path, which is the same scheme the
    other file-based caches use and the one an external consumer can
    reproduce without reading our code: sha1(canonical path).png.
    """
    key = hostos.canonical_path_key(hip_path or "")
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(thumb_dir(), digest + ".png")


def has_thumbnail(hip_path: str) -> bool:
    path = thumb_path(hip_path)
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _manifest_path() -> str:
    return os.path.join(thumb_dir(), "manifest.json")


def _record_manifest(hip_path: str, png: str) -> None:
    """Remember which scene a hash belongs to.

    The PNG name is a one-way hash, so without this the directory is
    unreadable by a human and unrecoverable if the mapping is ever
    needed in reverse. Written whole and small; a manifest that will
    not parse is REPLACED rather than merged, because losing the map is
    recoverable (re-capture) while refusing to record anything is not.
    """
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
        # ATOMIC, like every other durable JSON store in the package
        # (database, notes, tile_icons, gradients, versions, prefs,
        # library_policy, and the two sibling thumbnail manifests).
        # This was the one writer still opening the destination "w":
        # reproduced by dying partway through the dump, which left the
        # file truncated, and the next capture then read it as
        # unreadable and replaced it with a one-entry map - 50
        # scene-to-thumbnail mappings gone. The captures themselves
        # survive, but this map is the only thing making a directory of
        # one-way hashes readable, which is what the docstring above
        # says it is for.
        hostos.write_json_atomic(path, data, indent=2)
    except OSError as exc:
        debug.event("hip", "manifest not written", error=str(exc))


# --------------------------------------------------------- placeholder

# The one rasterisation this kept lives in `ui_helpers.svg_image` now,
# with the render it belonged to.


def placeholder_image():
    """The tile shown for a scene with no capture yet.

    Every other section renders a real preview on a cache miss; this one
    cannot, so the placeholder is not a "loading" state that will
    resolve on its own - it is the resting state until someone presses
    Capture. It therefore has to look deliberate rather than broken.

    The render and its cache are `ui_helpers.svg_image`, which the
    material library had a second copy of. This function stays because
    the CONCEPT is this section's - which SVG stands for a scene with
    no capture, and why it is a resting state - and that is not
    something a generic renderer knows.
    """
    return ui_helpers.svg_image("icon_hip.svg")


# ------------------------------------------------- which scene is open

#: Survives importlib.reload - the panel reloads modules in place and a
#: plain assignment would forget which scene Amaze opened every time.
_state = globals().get("_state", {"opened": ""})


def _key(path: str) -> str:
    """canonical_path_key, but "" stays "".

    os.path.normpath("") is ".", so an empty path became a TRUTHY key.
    Two guards depended on the empty case: `if not opened` never fired,
    and note_opened("") stored "." - which equals current_scene_path()
    when Houdini has no file open, so amaze_opened_current_scene()
    answered True for a scene Amaze never opened. A fail-OPEN in the one
    check that prevents mis-filing.
    """
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
    """Whether the scene on screen is the one Amaze opened.

    Compares the RECORDED path against what Houdini actually has open,
    rather than tracking load events. If the user opens something else
    by any means - File > Open, a recent-files entry, a crash recovery -
    the comparison simply stops matching, with no callback to register,
    no event to miss and nothing to get out of sync.
    """
    opened = opened_path()
    return bool(opened) and opened == current_scene_path()


# ------------------------------------------------- viewport state

#: Delegates that DRAW the viewport rather than render it. A capture
#: through one of these costs a raster frame - milliseconds. Measured
#: on 22.0.394 the delegate reports as "Houdini VK"; older builds
#: report "Houdini GL".
FAST_DELEGATES = ("houdini gl", "houdini vk")


def delegate_is_fast(name) -> bool:
    """Whether a capture through this Hydra delegate is cheap."""
    return str(name or "").strip().lower() in FAST_DELEGATES


def scene_viewer():
    """The scene view the user is actually looking at, or None.

    Order matters, and an earlier version of this had it BACKWARDS on a
    wrong reading of the stock helper. Read the shipped source before
    changing it: `toolutils.sceneViewer` (python3.*libs/toolutils.py)
    loops "find the first scene viewer tab which is the CURRENT tab in
    its pane" - it filters to a visible viewer. `paneTabOfType` is
    documented as plain indexing with no such filter, so it can hand
    back a viewer hidden behind another tab. Preferring it was a
    REGRESSION against the helper it was supposed to improve on.

    1. under the cursor - the one being pointed at;
    2. the stock helper, with can_switch_tabs=False so that merely
       ASKING never rearranges the user's panes (it defaults to True
       and will make a viewer current);
    3. any scene viewer at all, hidden or not, as a last resort.

    GUI only: every call here is behind hou.ui.
    """
    try:
        import hou
        tab = hou.ui.paneTabUnderCursor()
        if tab is not None and tab.type() == hou.paneTabType.SceneViewer:
            return tab
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import toolutils
        # Raises hou.NotAvailable when no scene viewer is current.
        viewer = toolutils.sceneViewer(can_switch_tabs=False)
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
    """The network category the Scene View is showing, lowercased.

    DIAGNOSTIC ONLY. A previous version used this to REFUSE a capture
    from a Cop network, on the reasoning that a COP has "nothing to
    photograph". That is wrong: browsing a copnet, the Scene View is
    still a real 3D perspective viewport - grid, axis gizmo, camera -
    with the COP output displayed on a card in space, and capturing it
    works. The refusal blocked legitimate work, and it was inferred from
    a log line rather than tested. Recorded here so the inference is not
    repeated: the network being browsed does NOT determine whether the
    viewport can be photographed.
    """
    try:
        pwd = viewer.pwd()
        category = pwd.childTypeCategory() if pwd else None
        return category.name().lower() if category else ""
    except Exception as exc:                             # noqa: BLE001
        # SAY WHY: "not a 3D context" and "we could not ask" must not
        # look the same, or this becomes the next unexplained refusal.
        debug.event("hip", "could not read the viewer context",
                    error="%s: %s" % (type(exc).__name__, exc))
        return ""


def viewport_state(viewer=None) -> dict:
    """What the scene view is doing, BEFORE asking it for a frame.

    Every image-producing route Houdini offers RENDERS - there is no
    call that copies the displayed frame (QWidget.grab() on the
    viewport's Vulkan surface hangs outright; wiki). So a capture costs
    whatever the active delegate costs, and with a pathtracer that is
    unbounded: a capture has been seen to block until a Karma render
    was stopped.

    Reading the state first turns that from a surprise into a choice.
    """
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
        # An OBJ viewport is not Hydra-based, so this raises there -
        # which is the ordinary case, not a warning sign. Blocking on
        # an unreadable renderer stopped every OBJ capture, so the rule
        # is: only stand in the way of a delegate we POSITIVELY
        # recognise as a renderer.
        state["error"] = str(exc)
    state["blocking"] = (
        state["readable"] and not delegate_is_fast(state["renderer"]))
    try:
        state["paused"] = bool(viewer.isRendererPaused())
    except Exception:                                    # noqa: BLE001
        state["paused"] = None
    return state


# ------------------------------------------------------------- capture

class CaptureRefused(Exception):
    """The capture did not happen, WITH the reason.

    Never a bare False: "no thumbnail appeared" and "the capture failed"
    must not look the same to a caller, which is the failure shape this
    project keeps rediscovering.
    """


def _looks_blank(png_path: str) -> bool:
    """True when the image carries no picture worth keeping.

    A capture taken before the viewport has drawn returns a single flat
    colour, and storing that is worse than storing nothing: it looks
    like the feature worked and it hides the scene behind a grey square
    forever. Sampled rather than scanned - a 1024px PNG has a million
    pixels and this runs on the UI thread.

    BLANK MEANS ONE COLOUR. The threshold used to be "more than two",
    which refused real frames: Houdini's shipped default scheme is flat
    black (3DSceneColors sets BackgroundBottomColor to @BackgroundColor),
    so a wireframe, flat-shaded or silhouette view samples exactly two.
    A sphere filling 60% of the frame was called blank, the user was
    told the viewport "had probably not finished drawing" - advice that
    can never work - and a deliberate frame could never replace an older
    one.

    The check is deliberately weak in the other direction and cannot be
    strong: on a GRADIENT background scheme an empty viewport already
    samples many colours, so "nothing was drawn" is not detectable that
    way at all. Catching the flat case is the whole of what this can
    honestly do.
    """
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
    """Capture the CURRENT scene view as this scene's thumbnail.

    Returns the PNG path. Raises CaptureRefused with a readable reason -
    the caller must always be able to tell the user WHY nothing
    happened.

    Uses husd.assetutils.saveThumbnailFromViewer, which SideFX ship
    identically in 21.0.790 and 22.0.394. Two arguments matter:

    - croptocamera=False. Cropping to the camera scales that crop into
      whatever resolution is asked for, so any mismatch between the
      request and the CAMERA's aperture distorts the image - SideFX's
      own res=(256, 256) default stretches every non-square camera.
      Capturing the whole viewport at its native aspect sidesteps the
      distortion entirely, needs no camera at all (most scenes here are
      OBJ-level and have none), and is what a scene view actually looks
      like. The tiles keep aspect and fill the background, so a
      non-square image is not a problem to solve.
    - res = the viewport's own pixel size, capped. Native aspect, no
      stretching.

    GUI ONLY: hou.ui does not exist headless, so this cannot run in
    hython. That is inherent - there is no viewport to capture.
    """
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
        # Resolved by the CALLER when there is one. Resolving again here
        # meant the guard and the shot could land on different
        # viewports: rung one is "under the cursor", so moving the mouse
        # between the two calls was enough - the guard cleared on the GL
        # viewport and the flipbook then ran on the Karma one, which is
        # exactly the unbounded block the guard exists to prevent.
        if viewer is None:
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

    # WHICH DELEGATE, and HOW LONG. The flipbook asks the viewport's
    # Hydra delegate for a frame, so the capture costs whatever that
    # delegate costs - and a pathtracer's frame has no upper bound.
    # Recorded BEFORE the call, because a record written only on
    # completion cannot distinguish "the user clicked late" from "the
    # capture blocked", which is exactly what the first report of this
    # could not answer.
    renderer = "unknown"
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
        # WHY, not just THAT. This fired from a Copernicus session and
        # the message named only the missing path, which sent the
        # diagnosis down a wrong road (a refusal that blocked a
        # perfectly capturable viewport). Record everything cheap that
        # could distinguish the causes, so the next occurrence is
        # readable from the log alone.
        detail = {"scratch": scratch, "context": viewer_context(viewer)}
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
    # Sweep any orphan left by an earlier scratch scheme, so a machine
    # upgrading into this code does not keep one forever: `.prev` from
    # the move-aside version, `.png.new` from the extension-breaking one,
    # and the FIXED `.capturing` name this replaced - a session killed
    # mid-capture under that scheme left exactly one, and now that the
    # name is unique nothing else would ever come back for it.
    _discard(out + ".prev")
    _discard(out + ".new")
    _discard(_legacy_capture_scratch(out))
    _record_manifest(hip_path, out)
    debug.event("hip", "thumbnail captured", file=hip_path, png=out,
                res=(width, height), renderer=renderer,
                seconds=round(time.time() - started, 2))
    # Tell every live model the file changed. Without this the capture
    # succeeds and the tile keeps showing the old picture, because the
    # engine is serving a decoded copy from memory - which is what the
    # shelf tool did on its first outing.
    try:
        signals.captured.emit(hip_path)
    except Exception as exc:                             # noqa: BLE001
        debug.event("hip", "could not announce the capture",
                    error=str(exc), file=hip_path)
    return out


def _capture_scratch(out: str) -> str:
    """The name Houdini writes a capture to before it is put in place.

    Three rules, each got wrong once. It is a function so a headless
    test can pin them; `capture_thumbnail` needs a live scene viewer.

    - Write ASIDE and replace. Never move the existing thumbnail out of
      the way first, or a crash mid-flipbook orphans the only copy.
    - The suffix goes BEFORE the extension. Houdini picks the format
      from the extension, so `out + ".new"` writes PIC2, which QImage
      reads as a blank frame. ▸r/image-extension
    - The name must be UNIQUE. `out` derives from the hip path, so a
      fixed scratch is one buffer shared by every session capturing that
      scene. ▸r/atomic-writes

    `create=False`, unlike every other caller: Houdini writes this file,
    which keeps `not os.path.isfile(scratch)` meaning "Houdini wrote
    nothing".
    """
    root, ext = os.path.splitext(out)
    return hostos.unique_scratch(out, suffix=".capturing" + (ext or ".png"),
                                 create=False)


def _legacy_capture_scratch(out: str) -> str:
    """The FIXED name this used before the unique one, so a machine
    upgrading into this code can be swept clean of the single leftover a
    session killed mid-capture left behind. Nothing else would ever come
    back for it now that the live name is unique."""
    root, ext = os.path.splitext(out)
    return root + ".capturing" + (ext or ".png")


def _discard(path: str) -> None:
    """Remove a scratch file, saying why if it will not go.

    Replaces the old _restore(): with the write-aside shape there is
    nothing to restore, because the live thumbnail is never moved."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        debug.event("hip", "could not remove a scratch thumbnail",
                    error=str(exc), path=path)


def capture_open_scene(target: str = "") -> str:
    """Capture the open scene as its thumbnail. THE decision path.

    Every refusal this feature can make lives here, so the panel button
    and the shelf tool cannot drift apart - the button used to hold the
    checks, the dialog and the refresh inline, which meant a second
    caller would have been a second copy of the policy.

    Callers do the reporting: this raises CaptureRefused with a
    readable reason and never touches hou.ui, which is also what keeps
    it testable headlessly.

    `target` empty (the shelf tool) means "whatever is open" - there is
    no tile to disagree with, so no mismatch is possible. `target` given
    (the tile menu) must MATCH what is open, or the capture would be
    filed under the wrong name.
    """
    opened = current_scene_path()
    if not target:
        if not opened:
            raise CaptureRefused(
                "No scene is open, so there is nothing to capture.")
        target = opened
    elif target != opened:
        # Say what is actually true. The old wording claimed the
        # viewport was showing a different scene even when it was
        # showing exactly this one and Amaze simply had not opened it -
        # a message that contradicted the screen.
        debug.event("hip", "capture refused - a different scene is open",
                    wanted=target, open=opened)
        raise CaptureRefused(
            "Houdini has a different scene open, so the capture would "
            "be filed under the wrong name.\n\n"
            "Open this scene first.")

    # An unsaved scene has a path that does not exist. Capturing it
    # wrote a PNG no tile can ever show and added a manifest entry for
    # a nonexistent file - and because the path is derived from the cwd,
    # every later unsaved session in that directory overwrote the same
    # slot.
    if not os.path.isfile(target):
        debug.event("hip", "capture refused - the scene is not on disk",
                    file=target)
        raise CaptureRefused(
            "This scene has not been saved yet, so there is nothing to "
            "file a thumbnail against.\n\nSave the scene first.")

    # Look at the viewport BEFORE asking it for a frame. Houdini has no
    # call that copies the displayed image - every route renders - so
    # with a pathtracing delegate the capture blocks for as long as that
    # render takes. Reading the state first turns an unbounded surprise
    # into a choice.
    viewer = scene_viewer()

    state = viewport_state(viewer)
    if state.get("blocking"):
        debug.event("hip", "capture refused - viewport is rendering",
                    renderer=state.get("renderer", ""),
                    error=state.get("error", ""))
        message = "Please stop the viewport render before capturing."
        if debug.is_on():
            # Debug Mode only. In normal use naming the renderer tells
            # the user what they already chose; when diagnosing, it is
            # the whole point.
            message += "\n\nDetected: %s" % (
                state.get("renderer") or "unreadable")
        raise CaptureRefused(message)
    return capture_thumbnail(target, viewer)


class _HipSignals(QtCore.QObject):
    """Relay for "a capture landed", so a capture from ANYWHERE repaints
    the tile.

    The shelf tool captured correctly and the tile did not change: the
    file on disk was replaced, but the engine keeps a decoded copy in
    memory and nothing told it otherwise. The panel button had always
    done that itself, right after its own call - which is exactly the
    shape that breaks the moment a second caller exists. The refresh is
    the CAPTURE's business, not the button's.
    """

    captured = QtCore.Signal(object)     # the scene path, replaced


# Reload-stable, the documented idiom: a module-level object rebuilt by
# `importlib.reload` would strand every connection made by the previous
# load, and the panel reloads its modules on every reopen.
#: Bumped whenever a signal is ADDED, REMOVED or changes arity. The
#: guard below compares it, because `hasattr` only proves a name is
#: present: changing `captured` to take two arguments left the old
#: one-argument relay in place for the rest of the session, `connect()`
#: succeeded, and the emit then raised TypeError - which the caller
#: swallows. Every tile would silently stop repainting, which is the
#: exact bug the relay was added to fix.
_RELAY_VERSION = 1

signals = globals().get("signals")
if signals is None or getattr(signals, "version", None) != _RELAY_VERSION:
    signals = _HipSignals()
    signals.version = _RELAY_VERSION


# -------------------------------------------------------------- models
