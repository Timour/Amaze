"""THE PREVIEW ENGINE - builds the scene a material thumbnail is shot in.

A ball, a floor, lights, a camera and a render node in a throwaway
subnet. The caller puts a material on the ball, renders one frame, keeps
the PNG and destroys the scene. WHEN a thumbnail is made and where it
goes belong to the callers, `core/thumbnails.py` and `render/thumbs.py`.

Inherited from egMatLib (github.com/eglaubauf/egMatLib, GPLv3) and still
the densest overlap left, which is why it is one package: a different
preview scene is then a replacement, not a hunt. ▸p/egmatlib-overlap

    ThumbNailScene(renderer)   "Redshift" or "Octane"; raises with no
                               Scene Viewer to read a colour space from
        .get_node()  .rop      the subnet, and the render node in it
    ocio_from_viewer()         display/view/working space, or None
    safe_set(node, parm, val)  set it if this build has that parm

Karma is not here - its scene is a USD stage, in `karma_scene`.

THE SUBNET'S SIX SPARE PARMS ARE AS MUCH THE CONTRACT as the names
above: `mat`, `path`, `res` (x, y), `obj_exclude`, `lights`, `render`.
Spell one differently and `safe_set` swallows it, so the failure is a
thumbnail-shaped no-op rather than a raise.

THE SCENE'S LIFETIME IS THE CALLER'S - no destroy is offered here.
`render/thumbs.py` builds inside `hou.undos.disabler()` and destroys in
a `finally`; without that an interrupted render leaves a live ROP in the
user's scene.
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
