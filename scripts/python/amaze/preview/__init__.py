"""THE PREVIEW ENGINE: the USD stage a thumbnail batch renders in ▸r/husk-startup"""
import importlib

from amaze.preview import thumbnail_scene
from amaze.preview import usd_scene

_LEAF_FIRST = (thumbnail_scene, usd_scene)

_DOOR = {
    "ocio_from_viewer": thumbnail_scene,
    "safe_set": thumbnail_scene,
    "build_usd_scaffold": usd_scene,
    "write_batch": usd_scene,
    "exr_to_png": usd_scene,
}

__all__ = list(_DOOR) + ["reload_engine"]


def _bind() -> None:
    """Point every name in `_DOOR` at what its module holds NOW. ▸p/preview-door"""
    globals().update({name: getattr(module, name)
                      for name, module in _DOOR.items()})


def reload_engine() -> None:
    """Re-execute this package's modules leaf first and re-bind them. ▸r/package-reload"""
    for module in _LEAF_FIRST:
        importlib.reload(module)
    _bind()


_bind()
