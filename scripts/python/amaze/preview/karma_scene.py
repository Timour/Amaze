"""The Karma preview scene: ONE USD stage composition, built by `build_karma_scaffold` and rendered into once per material by `render_karma_into`, so a batch pays the stage load once; THE CALLER NAMES THE OUTPUT FILE (`png_path`), exactly as it sets `path` on the other three renderers' own scenes."""
import os
import time

import hou

import amaze
from amaze.core import debug
from amaze.helpers import helpers, hostver
from amaze.preview import thumbnail_scene


def build_karma_scaffold(preferences):
    """The Karma thumbnail scaffold, built ONCE and rendered into once per material: lopnet, shaderball USD reference (the expensive part - a full stage composition), floor material, Karma render properties and ROP, every one of them identical for every material; a scaffold dict for `render_karma_into`, or None when no Scene Viewer is open to take the OCIO display/view from."""
    ocio = thumbnail_scene.ocio_from_viewer()
    if not ocio:
        return None

    display = ocio["display"]
    view = ocio["view"]
    space = ocio["space"]

    with hou.undos.disabler():    # THE WHOLE BUILD, not just the container: each createNode, parm set and flag here is its own undo entry and destroying the net afterwards removes none of them, so a thumbnail spent the artist's next Ctrl+Z on scaffold noise instead of their own last edit ▸r/undo-groups
        net = hou.node("/obj").createNode("lopnet")
        try:
            ref = net.createNode("reference::2.0")
            ref.parm("filepath1").set(
                amaze.package_file("res", "usd",
                                   "shaderBallScene_Simple.usd"))
            ref.parm("primpath1").set("/shaderBallScene")
            lib1 = net.createNode("materiallibrary")
            lib1.setFirstInput(ref)
            surf = lib1.createNode("mtlxstandard_surface")
            tex = lib1.createNode("mtlxtiledimage")
            tex.parm("file").set(
                "$AMAZE/scripts/python/amaze/res/img/FloorTexture.rat")
            surf.setInput(1, tex, 0)
            surf.setGenericFlag(hou.nodeFlag.Material, True)
            lib1.parm("materials").set(1)
            lib1.parm("matnode1").set("mtlxstandard_surface1")
            lib1.parm("matpath1").set("/thumb/bg_material")
            lib1.parm("geopath1").set("/shaderBallScene/geo/plane/mesh_0")
            lib1.parm("assign1").set(1)

            render_props = net.createNode("karmarenderproperties")
            render_props.parm("camera").set(
                "/shaderBallScene/cameras/RenderCam")
            render_props.parm("res_mode").set("manual")
            render_props.parm("res_mode").pressButton()
            render_props.parm("resolutionx").set(preferences.rendersize)
            render_props.parm("resolutiony").deleteAllKeyframes()
            render_props.parm("resolutiony").set(preferences.rendersize)
            render_props.parm("engine").set("cpu")    # CPU, not XPU: XPU's device startup dominates at thumbnail size, so it is the slower of the two here
            render_props.parm("engine").pressButton()
            render_props.parm("samplesperpixel").set(    # THE CPU DIAL (Primary Samples). The `pathtracedsamples` beside it is the XPU one - each hides when the other engine is chosen - so the samples preference has to follow whatever `engine` above is set to or it drives nothing. Karma's own pref, deliberately NOT `preferences.rendersamples`, which is the Redshift dial at a very different scale
                preferences.karma_rendersamples)
            render_props.parm("enabledof").set(0)
            render_props.parm("enablemblur").set(0)

            rop = net.createNode("usdrender_rop")
            rop.parm("renderer").set("BRAY_HdKarma")    # Karma CPU
            rop.setFirstInput(render_props)
            rop.parm("soho_foreground").set(1)
        except Exception:
            net.destroy()    # a half-built scaffold is never handed back, and the destroy is under the same disabler as the create
            raise
    return {
        "net": net,
        "lib1": lib1,
        "render_props": render_props,
        "rop": rop,
        "display": display,
        "view": view,
        "space": space,
    }


def render_karma_into(scaffold, node, asset_id: str, png_path: str) -> bool:
    """One material rendered into a pre-built scaffold and written to `png_path`, True only when that PNG is really there afterwards: creates and destroys ONLY the per-material nodes (material library, exr->png copnet) so the scaffold survives for the next material, and hands the artist back the undo stack and the selection it found. ▸r/undo-groups"""
    net = scaffold["net"]
    lib1 = scaffold["lib1"]
    render_props = scaffold["render_props"]
    rop = scaffold["rop"]
    display = scaffold["display"]
    view = scaffold["view"]
    space = scaffold["space"]

    path = "%s.%d.acescg.exr" % (    # UNIQUE per render (timestamp suffix): Houdini caches images by file path, so a rerender writing the same intermediate EXR name can have its EXR->PNG conversion served the PREVIOUS render's cached pixels - a fresh-looking PNG with stale content. Off the same composition as `png_path`, so intermediate and final can never land in different directories
        os.path.splitext(png_path)[0], int(time.time() * 1000))

    lib = None
    copnet = None
    with helpers.preserving_selection_and_current():    # `hou.copyNodesTo` below CLEARS the selection and selects its copies (documented), and the copies are destroyed at the end, so without this a thumbnail leaves the artist with nothing selected; restores on the interrupt and exception paths too. OUTSIDE the disabler, which it does not need - it opens its own for the restore, selection calls being undo entries ▸r/node-graph
        with hou.undos.disabler():    # THE WHOLE PER-MATERIAL RENDER, not only the staging pairs: every node operation in here is an undo entry that destroying the per-material nodes does not remove ▸r/undo-groups
            try:
                lib = net.createNode("materiallibrary")
                lib.setFirstInput(lib1)

                curr_items = node
                if not isinstance(node, list):
                    if curr_items.type().name() == "subnet":
                        curr_items = (node,)
                    elif "mtlxopen_pbr_surface" in curr_items.type().name():
                        curr_items = (node,)
                    else:
                        curr_items = node.children()

                with debug.timed("batch", "copy nodes into lib",
                                 asset_id=str(asset_id)):
                    curr_nodes = hou.copyNodesTo(curr_items, lib)  # type: ignore
                if curr_nodes:    # empty when the material is a builder subnet with zero children - nothing to select, nothing to render
                    curr_nodes[0].setSelected(True)

                mat_node = None
                for n in curr_nodes:
                    if n.type().name() == "collect":
                        n.setGenericFlag(hou.nodeFlag.Material, True)
                        mat_node = n

                if mat_node is None:
                    for n in curr_nodes:
                        if n.type().name() == "mtlxstandard_surface":
                            n.setGenericFlag(hou.nodeFlag.Material, True)
                            mat_node = n
                            break
                        elif "subnet" in n.type().name():
                            n.setGenericFlag(hou.nodeFlag.Material, True)
                            mat_node = n
                            break

                if debug.is_on():
                    debug.event(
                        "thumb", "karma material content",
                        asset_id=str(asset_id),
                        ocio_display=scaffold.get("display"),
                        ocio_view=scaffold.get("view"),
                        textures=(debug.texture_snapshot(curr_nodes[0])
                                  if curr_nodes else None),    # GUARDED like the identical index above: a diagnosis aid must never change the outcome, and an unguarded one here raises only for the people running with Debug Mode on
                    )
                debug.event(
                    "thumb", "karma material node chosen",
                    asset_id=str(asset_id),
                    mat_node=mat_node.name() if mat_node else None,
                    mat_type=mat_node.type().name() if mat_node else None,
                    candidates=[(n.name(), n.type().name())
                                for n in curr_nodes],
                )
                if mat_node is not None:
                    lib.parm("materials").set(1)    # ONE explicit entry, the pattern lib1 already uses, not `fillmaterials`: auto-fill writes an entry per material-ish node in the copied network and the extra entries' prims never generate, one yellow `Ignoring missing explicit primitive` node error each, on every render
                    lib.parm("matnode1").set(mat_node.name())
                    lib.parm("matpath1").set("/materials/" + mat_node.name())
                else:
                    lib.parm("fillmaterials").pressButton()    # no recognisable material node - auto-fill rather than render nothing
                lib.parm("assign1").set(1)
                lib.parm("geopath1").set("/shaderBallScene/geo/ball")

                render_props.parm("picture").set(path)
                render_props.setFirstInput(lib)

                with debug.timed("batch", "husk render (rop execute)",
                                 asset_id=str(asset_id)):
                    rop.parm("execute").pressButton()

                if not os.path.exists(path):
                    debug.event(    # the render produced nothing - fail loudly instead of letting the conversion write a PNG from stale data; the old PNG stays, honestly old
                        "thumb", "karma render produced no EXR",
                        asset_id=str(asset_id), expected=path,
                        rop=rop.path(),
                        rop_errors=helpers.node_errors(rop),
                        lib_errors=helpers.node_errors(lib),
                    )
                    debug.note("Karma thumbnail render produced no EXR for "
                               + str(asset_id)
                               + " - keeping the old thumbnail")
                    return False

                if hostver.has_new_cops():
                    copnet = net.createNode("copnet")
                    copnet.setName("exr_to_png", unique_name=True)

                    cop_file = copnet.createNode("file")
                    cop_file.parm("filename").set(path)
                    cop_file.parm("aovs").set(1)
                    cop_file.parm("aov1").set("C")
                    cop_out = copnet.createNode("rop_image")
                    cop_out.parm("trange").set(0)

                    cop_out.setInput(0, cop_file)
                    cop_out.parm("colorconversion").set(1)    # Bake OpenColorIO
                    cop_out.parm("ociodisplay").set(display)
                    cop_out.parm("ocioview").set(view)

                    cop_out.parm("copoutput").set(png_path)
                    with debug.timed("batch", "exr->png conversion",
                                     asset_id=str(asset_id)):
                        cop_out.parm("execute").pressButton()

                else:
                    copnet = net.createNode("cop2net")    # the old COPs, whose OCIO capabilities are more restricted
                    copnet.setName("exr_to_png", unique_name=True)

                    cop_file = copnet.createNode("file")
                    cop_file.parm("nodename").set(0)
                    cop_file.parm("filename1").set(path)
                    cop_file.parm("colorspace").set(3)    # OpenColorIO
                    cop_file.parm("ocio_space").set(space)
                    cop_out = copnet.createNode("rop_comp")
                    cop_out.parm("trange").set(0)

                    cop_out.setInput(0, cop_file)
                    cop_out.parm("convertcolorspace").set(3)
                    cop_out.parm("ocio_display").set(display)
                    cop_out.parm("ocio_view").set(view)

                    cop_out.parm("copoutput").set(png_path)
                    cop_out.parm("execute").pressButton()
            finally:
                if copnet is not None:    # ONLY the per-material nodes, so the scaffold stays clean for the next material; in the `finally`, so an interrupt leaves no orphaned material lib or copnet behind
                    copnet.destroy()
                if lib is not None:
                    lib.destroy()
                if os.path.exists(path):    # also INSIDE the finally: `hou.OperationInterrupted` from ESC used to propagate past the removal, and the names are timestamp-unique by design, so nothing ever reclaimed what an interrupted render left in the LIBRARY's image directory
                    try:
                        os.remove(path)
                    except OSError as exc:
                        debug.event(    # a held intermediate (sync client, viewer) must not fail the render
                            "thumb", "intermediate not removed",
                            path=path, error=str(exc))

    if debug.is_on():
        debug.event("thumb", "karma thumbnail written",    # measure the PNG that was actually written: at tile size an all-zero render, a transparent image and a stale file are indistinguishable by eye and are different bugs
                    asset_id=str(asset_id), **debug.image_stats(png_path))

    if not os.path.exists(png_path) or os.path.getsize(png_path) == 0:
        debug.event("thumb", "karma produced no PNG",    # THE OUTPUT IS CHECKED, not assumed - a copnet that would not cook, an unwritable `img/` or a rejected OCIO string otherwise read as success, and a failed render keeps the OLD thumbnail, so the tile shows the previous image and nothing says the new one never happened. The measurement above cannot do this job: it runs only under Debug Mode
                    asset_id=str(asset_id), path=png_path)
        return False

    return True
