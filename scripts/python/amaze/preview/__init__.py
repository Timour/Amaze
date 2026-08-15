"""THE PREVIEW ENGINE - builds the scene a material thumbnail is shot in.

A ball, a floor, lights, a camera and a render node in a throwaway
subnet. Inherited from egMatLib (GPLv3). ▸p/egmatlib-overlap

    ThumbNailScene(renderer)   "Redshift" or "Octane" (Karma's scene is
                               a USD stage, in `karma_scene`)
    ocio_from_viewer()         display/view/working space, or None
    safe_set(node, parm, val)  set it if this build has that parm

Drive it by setting six spare parms on the subnet: `mat`, `path`,
`res`, `obj_exclude`, `lights`, `render`. `safe_set` swallows a
misspelled parm, so a typo renders a no-op instead of raising.

The CALLER must destroy the scene - see `render/thumbs.py`.
"""
import importlib

from amaze.preview import shaderball_scene
from amaze.preview import thumbnail_scene
from amaze.preview import karma_scene

ThumbNailScene = thumbnail_scene.ThumbNailScene
ocio_from_viewer = thumbnail_scene.ocio_from_viewer
safe_set = thumbnail_scene.safe_set
build_karma_scaffold = karma_scene.build_karma_scaffold
render_karma_into = karma_scene.render_karma_into

__all__ = ["ThumbNailScene", "ocio_from_viewer", "safe_set",
           "build_karma_scaffold", "render_karma_into", "reload_engine"]


def reload_engine():
    """Re-execute this package's modules, leaf first, and re-bind.

    The panel's reload chain calls this instead of reloading the package,
    which would refresh nothing; re-binding is the half that is easy to
    drop. ▸r/package-reload
    """
    global ThumbNailScene, ocio_from_viewer, safe_set
    global build_karma_scaffold, render_karma_into
    importlib.reload(shaderball_scene)
    importlib.reload(thumbnail_scene)
    importlib.reload(karma_scene)
    ThumbNailScene = thumbnail_scene.ThumbNailScene
    ocio_from_viewer = thumbnail_scene.ocio_from_viewer
    safe_set = thumbnail_scene.safe_set
    build_karma_scaffold = karma_scene.build_karma_scaffold
    render_karma_into = karma_scene.render_karma_into
