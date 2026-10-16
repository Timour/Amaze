"""THE PREVIEW ENGINE - the throwaway subnet a material thumbnail is shot in; the CALLER destroys it (`render/thumbs.py`). Inherited from egMatLib (GPLv3). ▸p/egmatlib-overlap"""
import importlib

from amaze.preview import shaderball_scene
from amaze.preview import thumbnail_scene
from amaze.preview import usd_scene

_LEAF_FIRST = (shaderball_scene, thumbnail_scene, usd_scene)

_DOOR = {
    "ThumbNailScene": thumbnail_scene,
    "ocio_from_viewer": thumbnail_scene,
    "safe_set": thumbnail_scene,
    "rig_key": thumbnail_scene,
    "build_usd_scaffold": usd_scene,
    "render_usd_into": usd_scene,
}

__all__ = list(_DOOR) + ["reload_engine"]


def _bind() -> None:
    """Point every name in `_DOOR` at what its module holds NOW. ▸p/preview-door"""
    globals().update({name: getattr(module, name)
                      for name, module in _DOOR.items()})


def reload_engine() -> None:
    """Re-execute this package's modules leaf first and re-bind; reloading the package alone refreshes nothing. ▸r/package-reload"""
    for module in _LEAF_FIRST:
        importlib.reload(module)
    _bind()


_bind()
