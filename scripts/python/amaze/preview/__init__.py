"""THE PREVIEW ENGINE - the throwaway subnet a material thumbnail is shot in; the CALLER destroys it (`render/thumbs.py`). Inherited from egMatLib (GPLv3). ▸p/egmatlib-overlap"""
import importlib

from amaze.preview import shaderball_scene
from amaze.preview import thumbnail_scene
from amaze.preview import karma_scene

ThumbNailScene = thumbnail_scene.ThumbNailScene
ocio_from_viewer = thumbnail_scene.ocio_from_viewer
safe_set = thumbnail_scene.safe_set
rig_key = thumbnail_scene.rig_key
build_karma_scaffold = karma_scene.build_karma_scaffold
render_karma_into = karma_scene.render_karma_into

__all__ = ["ThumbNailScene", "ocio_from_viewer", "safe_set", "rig_key",
           "build_karma_scaffold", "render_karma_into", "reload_engine"]


def reload_engine():
    """Re-execute this package's modules leaf first and re-bind; reloading the package alone refreshes nothing. ▸r/package-reload"""
    global ThumbNailScene, ocio_from_viewer, safe_set, rig_key
    global build_karma_scaffold, render_karma_into
    importlib.reload(shaderball_scene)
    importlib.reload(thumbnail_scene)
    importlib.reload(karma_scene)
    ThumbNailScene = thumbnail_scene.ThumbNailScene
    ocio_from_viewer = thumbnail_scene.ocio_from_viewer
    safe_set = thumbnail_scene.safe_set
    rig_key = thumbnail_scene.rig_key
    build_karma_scaffold = karma_scene.build_karma_scaffold
    render_karma_into = karma_scene.render_karma_into
