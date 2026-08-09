"""THE PREVIEW ENGINE - the scene a material thumbnail is rendered in.

Every material tile in Amaze shows a rendered picture. To make one, a
little scene is built off to one side - a ball, a floor, lights, a
camera, an output node - the material is put on the ball, one frame is
rendered, the PNG is kept and the scene is destroyed again. This package
is that scene builder, and nothing else. It does not decide WHEN a
thumbnail is made, where the file goes, or what the grid does with it;
those belong to the Thumbnail Engine (core/thumbnails.py) and the
thumbnail runner (render/thumbs.py), which are this package's callers.

WHY IT IS A PACKAGE. Amaze began as a fork of egMatLib
(github.com/eglaubauf/egMatLib, GPLv3). This is the part of that
inheritance that is still doing a recognisable job of its own: measured
against upstream at 1e0480d, shaderball_scene is 70% verbatim and
thumbnail_scene 42%, and the art these modules load - the shaderball
geometry, the floor textures, the studio HDRI, the USD shaderball
scenes - is byte-identical to what upstream ships. Boxing it says that
plainly in one place instead of leaving it smeared through the render
stack, and it means a different preview scene is one package to
replace rather than a hunt.

TWO HONESTY CLAUSES, so this is never oversold:

  * It changes engineering and framing, NOT the licence of the shipped
    whole. GPLv3 binds while any derived line ships, here or anywhere
    else in Amaze.
  * A later full swap would improve the position but stays grey without
    a clean-room rewrite. This package is not a licence boundary.

WHAT IS NOT UPSTREAM'S, so a swap does not throw it away: `safe_set` is
Amaze's, written because renderer builds rename their parameters between
releases and the alternative was an AttributeError that aborts the
render. It is exported here because every caller of this engine needs it
to talk to the node the engine returns.

=========================================================================
THE API
=========================================================================

    ThumbNailScene(renderer)      build a scene for "Mantra",
                                  "Redshift" or "Octane". Raises if
                                  there is no Scene Viewer to read a
                                  colour space from.
        .get_node()               the subnet it built
        .rop                      the render node inside it - a
                                  different type per renderer

    ocio_from_viewer()            the Scene Viewer's OCIO display, view
                                  and working space, or None. The seam
                                  the tests replace.

    safe_set(node, parm, value)   set a parameter if this renderer build
                                  has it; log and carry on if not.

AND THE PART THAT IS NOT PYTHON. The scene returned by `get_node()`
carries seven spare parameters, and the caller drives the engine by
setting them. They are as much the contract as the names above, and a
replacement engine that spells one differently produces a
thumbnail-shaped no-op rather than an error, because `safe_set`
deliberately swallows a missing parameter:

    mat            the material to put on the ball
    path           where the render is written
    cop_out_img    where the converted PNG is written
    resx  resy     the render size
    obj_exclude    what the render must not see
    lights         which lights it uses
    render         the button that executes it

THE SCENE'S LIFETIME IS THE CALLER'S. This package creates a subnet in
/obj and offers no destroy: `render/thumbs.py` builds inside
`hou.undos.disabler()` and destroys in a `finally`. That pairing is not
optional - without it an interrupted render leaves a live ROP in the
user's scene, which is how a runaway re-render was found once already.
"""
import importlib

from amaze.preview import shaderball_scene
from amaze.preview import thumbnail_scene

ThumbNailScene = thumbnail_scene.ThumbNailScene
ocio_from_viewer = thumbnail_scene.ocio_from_viewer
safe_set = thumbnail_scene.safe_set

__all__ = ["ThumbNailScene", "ocio_from_viewer", "safe_set", "reload_engine"]


def reload_engine():
    """Re-execute this package's modules, leaf first, and re-bind.

    THE PANEL'S RELOAD CHAIN CALLS THIS, and it cannot simply reload the
    package instead: `importlib.reload` on a package re-runs only this
    file, and the `from ... import` lines above find both submodules
    already in sys.modules and hand back the cached ones. The chain
    would look complete and refresh nothing.

    The re-binding matters for the same reason `base_dialog` is reloaded
    before `gradient_dialog`: the three names above are bound to the
    objects that existed when this file last ran, so reloading the
    submodules without re-reading them leaves callers holding the old
    class (verified once already - AssetDialog's identity survived a
    panel reopen, so editing it needed a full Houdini restart).
    """
    global ThumbNailScene, ocio_from_viewer, safe_set
    importlib.reload(shaderball_scene)
    importlib.reload(thumbnail_scene)
    ThumbNailScene = thumbnail_scene.ThumbNailScene
    ocio_from_viewer = thumbnail_scene.ocio_from_viewer
    safe_set = thumbnail_scene.safe_set
