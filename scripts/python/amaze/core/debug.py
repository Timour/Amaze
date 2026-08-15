"""The debug engine: a structured session log, off unless asked for. ▸o/debug-engine"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import sys
import threading
import time
import traceback
from contextlib import contextmanager

from amaze.helpers import hostos

DEFAULT_DIR = os.environ.get("AMAZE_LOG_DIR", "").strip() or hostos.log_root()
DEFAULT_NAME = "amaze_debug.jsonl"
LEGACY_NAME = "assetlib_debug.jsonl"


def _migrate_legacy_log(directory: str) -> None:
    """Carry an existing log forward under the new name, once; a failure here costs the old file, never logging."""
    hostos.migrate_legacy_file(directory, LEGACY_NAME, DEFAULT_NAME)


_migrate_legacy_log(DEFAULT_DIR)

import atexit  # noqa: E402 - registered once, below the log path setup

MAX_BYTES = 32 * 1024 * 1024

_enabled = False
_path = os.path.join(DEFAULT_DIR, DEFAULT_NAME)
_session = ""
_seq = 0
_excepthook_installed = globals().get("_excepthook_installed", False)
_crash_counts: dict = {}

FLOOD_VERBATIM = 5
FLOOD_MARKER_EVERY = 1000
FLOOD_DECAY_SECONDS = 300

_crash_recorded: dict = globals().get("_crash_recorded", {})
_crash_last_seen: dict = globals().get("_crash_last_seen", {})


def _flood_check(kind: str, exc_type_name: str, tb_text: str):
    """Rate-limit an identical, repeating failure; (record_it, count). ▸o/debug-engine"""
    frame = ""
    lines = tb_text.splitlines()
    if len(lines) >= 2:
        frame = lines[-2].strip()
    key = "%s|%s|%s" % (kind, exc_type_name, frame)

    now = time.monotonic()
    last = _crash_last_seen.get(key)
    if last is not None and now - last > FLOOD_DECAY_SECONDS:
        _flush_repeat(key)
        _crash_counts.pop(key, None)
        _crash_recorded.pop(key, None)
    _crash_last_seen[key] = now

    count = _crash_counts.get(key, 0) + 1
    _crash_counts[key] = count
    if count <= FLOOD_VERBATIM:
        _crash_recorded[key] = _crash_recorded.get(key, 0) + 1
        return True, count
    power_of_ten = count == 10 ** (len(str(count)) - 1)
    if power_of_ten or count % FLOOD_MARKER_EVERY == 0:
        _crash_recorded[key] = _crash_recorded.get(key, 0) + 1
        return True, count
    return False, count


def _suppressed_for(kind: str, exc_type_name: str, tb_text: str, count: int) -> int:
    """How many of this key's occurrences never reached the log - counted, never inferred."""
    frame = ""
    lines = tb_text.splitlines()
    if len(lines) >= 2:
        frame = lines[-2].strip()
    key = "%s|%s|%s" % (kind, exc_type_name, frame)
    return max(count - _crash_recorded.get(key, 0), 0)


def _flush_repeat(key: str) -> None:
    """A key's EXACT total, categorised by the key so a flood of ordinary events is not filed as a crash."""
    count = _crash_counts.get(key)
    if not count:
        return
    recorded = _crash_recorded.get(key, 0)
    if count <= FLOOD_VERBATIM:
        return
    kind, _, rest = key.partition("|")
    exc_name, _, frame = rest.partition("|")
    _ensure_session()
    cat = "flood"
    if kind.startswith("event:"):
        cat = kind.split(":", 1)[1].strip() or "flood"
    elif kind:
        cat = kind.strip()
    _write({
        "cat": cat,
        "msg": "%s: %s (final count)" % (kind, exc_name),
        "data": {
            "repeat_count": count,
            "suppressed": count - recorded,
            "frame": frame,
        },
    })


def flush_repeats() -> None:
    """Every rate-limited failure's final count, registered at exit."""
    for key in list(_crash_counts):
        try:
            _flush_repeat(key)
        except Exception:               # noqa: BLE001 - never block exit
            pass
        _crash_counts.pop(key, None)
        _crash_recorded.pop(key, None)
_previous_excepthook = globals().get("_previous_excepthook")
_installed = globals().get("_installed", False)
_rotation_blocked = False

_pass_spent: dict = globals().get("_pass_spent", {})


def begin_pass(name: str) -> None:
    """Start a pass, giving its per-item records a fresh allowance."""
    _pass_spent[name] = 0


def pass_budget(name: str, cap: int) -> bool:
    """True while this pass may still record a per-item diagnostic; call `begin_pass` to refresh the allowance."""
    if _pass_spent.get(name, 0) >= cap:
        return False
    _pass_spent[name] = _pass_spent.get(name, 0) + 1
    return True


def guarded(where: str):
    """Wrap a Qt slot: PySide SWALLOWS its exceptions, so record always - crash tier - then re-raise."""
    def _wrap(fn):
        import functools

        @functools.wraps(fn)
        def _inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                exc_type, exc_value, exc_tb = sys.exc_info()
                _ensure_session()
                tb_text = "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                )
                keep, count = _flood_check(
                    "slot:%s" % where, exc_type.__name__, tb_text
                )
                if keep:
                    record = {
                        "cat": "exception",
                        "msg": "slot crash in %s: %s"
                               % (where, exc_type.__name__),
                        "data": {"value": str(exc_value)},
                        "traceback": tb_text,
                    }
                    if count > FLOOD_VERBATIM:
                        record["data"]["repeat_count"] = count
                        record["data"]["suppressed"] = _suppressed_for(
                            "slot:%s" % where, exc_type.__name__,
                            tb_text, count)
                    _write(record)
                raise
        return _inner
    return _wrap


def probe() -> dict:
    """Live engine state; a `module_id` disagreeing with the session header means two module objects. ▸r/module-reload"""
    return {
        "module_id": id(sys.modules.get(__name__)),
        "module_name": __name__,
        "enabled": _enabled,
        "session_id": _session,
        "path": _path,
    }


class ExportRefused(Exception):
    """The export could not be made, WITH the reason - never a bare False an empty log would also return."""


def export_log(dest_dir: str) -> str:
    """Snapshot the log into `dest_dir` as `amaze-<machine>-<os>-hou<version>-<stamp>.jsonl`; raises ExportRefused with a reason to show."""
    source = log_path()
    if not dest_dir:
        raise ExportRefused("No destination folder was chosen.")
    if not os.path.exists(source):
        raise ExportRefused(
            "There is no log yet at %s - turn Debug Mode on, reproduce "
            "the problem, then export." % source)
    try:
        if os.path.getsize(source) == 0:
            raise ExportRefused(
                "The log exists but is empty - turn Debug Mode on and "
                "reproduce the problem first.")
    except OSError as exc:
        raise ExportRefused("Could not read the log: %s" % exc)

    try:
        version = _houdini_version_tag()
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = "amaze-%s-%s-hou%s-%s.jsonl" % (
            hostos.machine_name(), hostos.os_tag(), version, stamp)
        target = os.path.join(dest_dir, name)
        suffix = 1
        while os.path.exists(target):
            target = os.path.join(
                dest_dir, name[:-6] + "-%d.jsonl" % suffix)
            suffix += 1
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as exc:
        raise ExportRefused(
            "Could not write to %s: %s" % (dest_dir, exc))
    event("prefs", "log exported",
          to=target, bytes=os.path.getsize(target))
    return target


def _houdini_version_tag() -> str:
    """The running Houdini version, filename-safe, or "unknown"."""
    try:
        import hou
        return str(hou.applicationVersionString()).replace(".", "-")
    except Exception:                                    # noqa: BLE001
        return "unknown"


def log_path() -> str:
    """Where the log is written (shown in Preferences)."""
    return _path


def _blank_slate(forget_alerts: bool = False) -> None:
    """The state a NEW file starts from; alerts are the user's, so only a clear drops them. ▸p/log-blank-slate"""
    global _session, _seq, _rotation_blocked
    _session = ""
    _seq = 0
    _rotation_blocked = False
    _crash_counts.clear()
    _crash_recorded.clear()
    _crash_last_seen.clear()
    if forget_alerts:
        _alerted.clear()


def clear_log() -> tuple:
    """Empty the log and head a fresh session over it; (ok, reason), reason "" on success."""
    try:
        if os.path.exists(_path):
            os.remove(_path)
    except OSError as exc:
        return False, str(exc)
    _blank_slate(forget_alerts=True)
    _ensure_session()
    return True, ""


def is_on() -> bool:
    """Guard expensive data-gathering at the call site with this."""
    return _enabled


def install() -> None:
    """Arm the crash recorder once at panel construction; it captures UNCAUGHT exceptions whatever Debug Mode says."""
    global _installed
    if _installed:
        return
    _installed = True
    _install_excepthook()


def _ensure_session() -> None:
    """Start a session and write its header if none has begun, so even a crash-only log carries the environment."""
    global _session
    if not _session:
        _session = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        _rotate()
        _write_session_header()


def configure(enabled: bool, path: str = "") -> None:
    """The user's VERBOSE switch, with a changed path starting a new file; crash capture is separate and always on."""
    global _enabled, _path
    was_on = _enabled
    enabled = bool(enabled)
    if path and path != _path:
        _path = path
        _blank_slate()
    elif path:
        _path = path
    if was_on and not enabled:
        event("session", "debug mode turned off")
    _enabled = enabled
    install()
    if _enabled and not _session:
        _ensure_session()
        event("session", "debug mode on")


def redirect(path: str) -> None:
    """Move the log to another FILE without touching Debug Mode, for a process that must not write the real one."""
    global _path
    _path = str(path)
    _blank_slate()


def _rotate() -> None:
    global _rotation_blocked
    try:
        if not (os.path.exists(_path) and os.path.getsize(_path) > MAX_BYTES):
            return
    except OSError:
        return
    try:
        os.replace(_path, _path + ".1")
        return
    except OSError:
        pass
    # A Windows reader's handle blocks the rename, a deny-write one blocks the truncate too. ▸r/failed-write
    try:
        shutil.copyfile(_path, _path + ".1")
        open(_path, "w", encoding="utf-8").close()
    except OSError:
        _rotation_blocked = True


def _write(record: dict) -> None:
    global _seq
    with _write_lock:
        _seq += 1
        record["n"] = _seq
        _write_locked(record)
    _maybe_rotate_inline()


def _write_locked(record: dict) -> None:
    """The write itself, called with `_write_lock` held; `encoding=` is load-bearing on Windows. ▸r/platform-files"""
    record["t"] = round(
        datetime.datetime.now().timestamp(), 3
    )
    record["clock"] = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    record["session"] = _session
    try:
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=_stringify) + "\n")
    except Exception:
        pass


_SIZE_CHECK_EVERY = 500

_write_lock = globals().get("_write_lock") or threading.Lock()


def _maybe_rotate_inline() -> None:
    """Enforce MAX_BYTES DURING a session, not only at its start - a long Houdini session is when it matters."""
    if _seq % _SIZE_CHECK_EVERY:
        return
    try:
        if os.path.getsize(_path) > MAX_BYTES:
            _rotate()
    except OSError:
        pass


def _stringify(value):
    """Anything not JSON-native (hou.Node, QImage, Sdf.Path...) becomes its repr rather than killing the write."""
    try:
        return str(value)
    except Exception:
        return "<unserialisable>"


def _app_version() -> str:
    """The released version, imported late because `debug` sits below `branding` in the import order."""
    try:
        from amaze import branding

        return str(branding.APP_VERSION)
    except Exception:                                       # noqa: BLE001
        return "unknown"


def _write_session_header() -> None:
    """The environment, once per session: build, Python, platform, Houdini, all three UI scales, renderer plugins."""
    info = {
        "module_id": id(sys.modules.get(__name__)),
        "amaze_version": _app_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "assetlib_env": os.environ.get("AMAZE", os.environ.get("ASSETLIB", "")),
    }
    try:
        import hou

        info["houdini"] = hou.applicationVersionString()
        info["product"] = hou.applicationName()
        try:
            info["ui_scale"] = float(hou.ui.globalScaleFactor())
        except Exception:
            pass
        try:
            from PySide6 import QtGui

            screen = QtGui.QGuiApplication.primaryScreen()
            if screen is not None:
                info["device_pixel_ratio"] = float(screen.devicePixelRatio())
        except Exception:
            pass
        try:
            from amaze.helpers import theme

            info["effective_ui_scale"] = float(theme.UI_SCALE)
        except Exception:
            pass
        for label, type_name in (
            ("redshift", "redshift_vopnet"),
            ("octane", "octane_vopnet"),
            ("mtlx", "mtlxstandard_surface"),
        ):
            info["has_" + label] = bool(
                hou.vopNodeTypeCategory().nodeTypes().get(type_name)
            )
    except Exception as exc:
        info["houdini_probe_failed"] = str(exc)
    info["debug_mode"] = _enabled
    _write({"cat": "session", "msg": "session start", "data": info})


def prefs_snapshot(preferences) -> None:
    """The COMPLETE settings state, always on: it is the RESTORE SOURCE when settings.json is lost, so it mirrors rather than samples."""
    if preferences is None:
        return
    _ensure_session()
    data = {}
    try:
        refresh = getattr(preferences, "refresh_data", None)
        snapshot = refresh() if callable(refresh) else getattr(
            preferences, "data", {}
        )
        data.update(dict(snapshot or {}))
    except Exception as exc:
        data["snapshot_failed"] = str(exc)
    for key in ("dir", "view_mode"):
        try:
            data["live_" + key] = getattr(preferences, key)
        except Exception:
            pass
    try:
        data["live_section_filters"] = dict(
            getattr(preferences, "_section_filters", {}))
    except Exception:
        pass
    _write({"cat": "session", "msg": "preferences", "data": data})


def event(category: str, message: str, /, **data) -> None:
    """A structured entry, silent with Debug Mode off; the `/` keeps `category`/`message` free for **data to reuse."""
    if not _enabled or _rotation_blocked:
        return
    keep, count = _flood_check("event:%s" % category, message, "")
    if not keep:
        return
    if count > FLOOD_VERBATIM:
        data = dict(data, repeat_count=count)
    _write({"cat": category, "msg": message, "data": data})


def note(message: str, /, **data) -> None:
    """Print `Amaze: ...` AND record it - but never print on Windows, where any print pops the Console open. ▸r/platform-files"""
    if _enabled and not _rotation_blocked:
        _write({"cat": "note", "msg": message, "data": data})
    try:
        from amaze.helpers import hostos
        if hostos.is_windows():
            return
    except Exception:                                    # noqa: BLE001
        pass
    print("Amaze: " + message)


_alerted: set = globals().get("_alerted", set())


def alert(message: str, /, key: str = "", **data) -> bool:
    """Interrupt ONCE per key for something rare and important, True when it showed; a formatted message MUST pass a stable `key`. ▸p/dialogs-are-a-bill ▸p/queue-time-needs"""
    stable = key or message
    if _enabled and not _rotation_blocked:
        _write({"cat": "alert", "msg": message,
                "data": dict(data, key=stable,
                             repeat=stable in _alerted)})
    if stable in _alerted:
        return False
    _alerted.add(stable)
    try:
        import hou
        from PySide6 import QtCore

        if not hasattr(hou, "ui"):
            raise AttributeError("no hou.ui in this session")
        QtCore.QTimer.singleShot(0, lambda: hou.ui.displayMessage(
            message, severity=hou.severityType.Warning,  # type: ignore
            title="Amaze",
        ))
        return True
    except Exception:                                    # noqa: BLE001
        print("Amaze: " + message)
        return True


def exception(where: str, exc: BaseException | None = None, /, **data) -> None:
    """A full traceback for a HANDLED exception, Debug-Mode gated; an UNCAUGHT one goes through `install()` regardless."""
    if not _enabled or _rotation_blocked:
        return
    text = traceback.format_exc() if exc is None else "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    keep, count = _flood_check(
        "handled:%s" % where,
        type(exc).__name__ if exc is not None else "Exception",
        text,
    )
    if not keep:
        return
    if count > FLOOD_VERBATIM:
        data = dict(data, repeat_count=count,
                    suppressed=_suppressed_for(
                        "handled:%s" % where,
                        type(exc).__name__ if exc is not None else "Exception",
                        text, count))
    _write({
        "cat": "exception",
        "msg": where,
        "data": data,
        "traceback": text,
    })


@contextmanager
def timed(category: str, message: str, /, **data):
    """Time a block and record the duration in `ms`, with `failed` set if it raised."""
    if not _enabled or _rotation_blocked:
        yield
        return
    start = datetime.datetime.now()
    failed = None
    try:
        yield
    except BaseException as exc:      # noqa: BLE001 - re-raised below
        failed = exc
        raise
    finally:
        ms = (datetime.datetime.now() - start).total_seconds() * 1000.0
        payload = dict(data)
        payload["ms"] = round(ms, 1)
        if failed is not None:
            payload["failed"] = str(failed)
        _write({"cat": category, "msg": message, "data": payload})


def image_stats(path: str) -> dict:
    """Measure a rendered image so a black-looking tile becomes a `verdict`: all black, fully transparent, or has content."""
    info = {"path": path}
    try:
        info["exists"] = os.path.exists(path)
        if not info["exists"]:
            return info
        info["bytes"] = os.path.getsize(path)
        info["mtime_age_s"] = round(
            datetime.datetime.now().timestamp() - os.path.getmtime(path), 1
        )
        from PySide6 import QtGui

        image = QtGui.QImage(path)
        if image.isNull():
            info["unreadable"] = True
            return info
        info["size"] = "%dx%d" % (image.width(), image.height())
        info["has_alpha"] = image.hasAlphaChannel()
        step = max(1, min(image.width(), image.height()) // 32)
        total = black = transparent = 0
        lum_sum = 0.0
        lum_max = 0.0
        for y in range(0, image.height(), step):
            for x in range(0, image.width(), step):
                colour = image.pixelColor(x, y)
                lum = (
                    0.2126 * colour.redF()
                    + 0.7152 * colour.greenF()
                    + 0.0722 * colour.blueF()
                )
                lum_sum += lum
                lum_max = max(lum_max, lum)
                if lum < 0.004:
                    black += 1
                if colour.alphaF() < 0.004:
                    transparent += 1
                total += 1
        if total:
            info["mean_luminance"] = round(lum_sum / total, 4)
            info["max_luminance"] = round(lum_max, 4)
            info["percent_black"] = round(100.0 * black / total, 1)
            info["percent_transparent"] = round(100.0 * transparent / total, 1)
            info["verdict"] = (
                "fully transparent" if transparent == total
                else "all black" if black == total
                else "mostly black" if black > total * 0.95
                else "has content"
            )
    except Exception as exc:
        info["stats_failed"] = str(exc)
    return info


def material_snapshot(shader, builder=None) -> dict:
    """A shading network's effective inputs and what drives each; pass `builder` to flag a promoted parm that DIFFERS."""
    if shader is None:
        return {}
    info = {}
    try:
        info["shader"] = shader.name()
        info["shader_type"] = shader.type().name()
        inputs = {}
        for name, source in zip(shader.inputNames(), shader.inputs()):
            parm = shader.parmTuple(name) or shader.parm(name)
            entry = {"driven_by": source.name() if source else None}
            if parm is not None:
                try:
                    entry["value"] = str(parm.eval())
                except Exception:
                    pass
            if builder is not None and source is not None and \
                    source.type().name() == "parameter":
                promoted = builder.parmTuple(name) or builder.parm(name)
                if promoted is not None:
                    try:
                        promoted_value = str(promoted.eval())
                        if promoted_value != entry.get("value"):
                            entry["promoted_DIFFERS"] = promoted_value
                    except Exception:
                        pass
            if source is not None or entry.get("value") not in (None, "(0.0,)"):
                inputs[name] = entry
        info["inputs"] = inputs
    except Exception as exc:
        info["snapshot_failed"] = str(exc)
    return info


def texture_snapshot(root) -> list:
    """Every file reference under a network and whether it resolves - a missing one renders black, silently."""
    out = []
    if root is None:
        return out
    try:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.isNetwork():
                stack.extend(node.children())
            for parm in node.parms():
                try:
                    template = parm.parmTemplate()
                    import hou

                    if not isinstance(template, hou.StringParmTemplate):
                        continue
                    if template.stringType() != hou.stringParmType.FileReference:
                        continue
                except Exception:
                    continue
                value = parm.eval()
                if not value:
                    continue
                out.append({
                    "node": node.name(),
                    "parm": parm.name(),
                    "path": value,
                    "exists": os.path.exists(value),
                })
    except Exception as exc:
        out.append({"snapshot_failed": str(exc)})
    return out


def node_snapshot(node, depth: int = 1) -> dict:
    """A node's type, shader language, children and their wiring, `depth` levels down."""
    if node is None:
        return {}
    try:
        info = {
            "path": node.path(),
            "type": node.type().name(),
            "is_network": node.isNetwork(),
        }
        try:
            info["shader_language"] = node.shaderLanguageName()
        except Exception:
            pass
        for parm_name in ("shader_rendercontextname", "tabmenumask"):
            parm = node.parm(parm_name)
            if parm is not None:
                info[parm_name] = parm.eval()
        if depth > 0 and node.isNetwork():
            children = []
            for child in node.children():
                entry = {
                    "name": child.name(),
                    "type": child.type().name(),
                }
                try:
                    entry["inputs"] = [
                        i.name() if i else None for i in child.inputs()
                    ]
                except Exception:
                    pass
                children.append(entry)
            info["children"] = children
            info["child_count"] = len(children)
        return info
    except Exception as exc:
        return {"snapshot_failed": str(exc)}


def _install_excepthook() -> None:
    """Capture PROPAGATING exceptions; its flags and `_previous_excepthook` must survive reload or the hook chains to itself. ▸r/module-reload"""
    global _excepthook_installed, _previous_excepthook
    if _excepthook_installed:
        return
    if getattr(sys.excepthook, "__module__", "") == __name__:
        _excepthook_installed = True
        return
    _previous_excepthook = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        """Record ALWAYS, flood-guarded, then chain to whatever was there before."""
        try:
            _ensure_session()
            tb_text = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            )
            keep, count = _flood_check(
                "unhandled", exc_type.__name__, tb_text
            )
            if not keep:
                return
            record = {
                "cat": "exception",
                "msg": "unhandled: %s" % exc_type.__name__,
                "data": {"value": str(exc_value)},
                "traceback": tb_text,
            }
            if count > FLOOD_VERBATIM:
                record["data"]["repeat_count"] = count
                record["data"]["suppressed"] = _suppressed_for(
                    "unhandled", exc_type.__name__, tb_text, count)
            _write(record)
        finally:
            if _previous_excepthook is not None:
                _previous_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
    _excepthook_installed = True


atexit.register(flush_repeats)
