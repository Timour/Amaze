"""The Karma preview scene: a USD stage, built once, rendered into many.

The other three renderers get a fresh scene per material
(`thumbnail_scene.ThumbNailScene`). Karma's is a full USD stage
composition, which is the expensive half, so it is built ONCE and each
material is rendered into it: `build_karma_scaffold` makes the stage,
`render_karma_into` puts one material on the ball and renders a frame.
Render All pays the stage load once for the whole batch; a single
render builds and destroys its own.

THE CALLER NAMES THE OUTPUT FILE, exactly as it does for the other
three - they set the scene's `path` parameter, this takes `png_path`.
It used to compute the path itself from the library's own layout, which
meant the preview engine knew where a library thumbnail lives; the
other renderers' path never did, and a replacement engine should not
have to learn Amaze's file layout to be swapped in.
"""
import os
import time

import hou

import amaze
from amaze.core import debug
from amaze.helpers import helpers, hostver
from amaze.preview import thumbnail_scene


def build_karma_scaffold(preferences):
    """Build the reusable Karma thumbnail scaffold ONCE: the lopnet, the
    shaderball USD reference (the expensive part - a full stage
    composition), the floor material, the Karma render properties and
    the ROP. Everything here is identical for every material - only the
    material library and output paths change per render (see
    render_karma_into). Returns a scaffold dict, or None if no Scene
    Viewer is open (OCIO display/view come from it).
    """
    ocio = thumbnail_scene.ocio_from_viewer()
    if not ocio:
        return None

    display = ocio["display"]
    view = ocio["view"]
    space = ocio["space"]

    # OFF the undo stack, like create_thumb_sop's container and
    # for the reason research.md ▸ Undo names thumbnails for
    # explicitly. Measured: this pair on the live stack comes
    # back on ONE Ctrl+Z, carrying the shaderball reference and
    # a live usdrender_rop; inside a disabler it does not.
    with hou.undos.disabler():
        net = hou.node("/obj").createNode("lopnet")
    try:
        ref = net.createNode("reference::2.0")
        # ONE scene. The Complex (V1) shaderball and its preference
        # were removed 2026-07-31: two scenes meant every thumbnail
        # bug had two reproductions, and the V1 assets were 75MB of
        # payload for an option nobody chose.
        ref.parm("filepath1").set(
            amaze.package_file("res", "usd", "shaderBallScene_Simple.usd"))

        ref.parm("primpath1").set("/shaderBallScene")
        lib1 = net.createNode("materiallibrary")
        lib1.setFirstInput(ref)
        surf = lib1.createNode("mtlxstandard_surface")
        tex = lib1.createNode("mtlxtiledimage")
        tex.parm("file").set("color3")
        tex.parm("file").set("$AMAZE/scripts/python/amaze/res/img/FloorTexture.rat")
        surf.setInput(1, tex, 0)
        surf.setGenericFlag(hou.nodeFlag.Material, True)
        lib1.parm("materials").set(1)
        lib1.parm("matnode1").set("mtlxstandard_surface1")
        lib1.parm("matpath1").set("/thumb/bg_material")
        lib1.parm("geopath1").set("/shaderBallScene/geo/plane/mesh_0")
        lib1.parm("assign1").set(1)

        # `render_props`, not `preferences`: the settings object is the
        # argument now, and two things called preferences in one scope
        # is how the wrong one gets read.
        render_props = net.createNode("karmarenderproperties")
        render_props.parm("camera").set("/shaderBallScene/cameras/RenderCam")
        render_props.parm("res_mode").set("manual")
        render_props.parm("res_mode").pressButton()
        render_props.parm("resolutionx").set(preferences.rendersize)
        render_props.parm("resolutiony").deleteAllKeyframes()
        render_props.parm("resolutiony").set(preferences.rendersize)
        # CPU engine, not XPU - much faster for small images like
        # these thumbnails (XPU's device startup overhead dominates
        # at this size). Samples from the Karma-specific pref
        # (default 9, Karma's own default) - deliberately NOT
        # prefs.rendersamples, which is the Redshift thumbnail dial
        # and lives at a very different scale (256).
        render_props.parm("engine").set("cpu")
        render_props.parm("engine").pressButton()
        render_props.parm("pathtracedsamples").set(
            preferences.karma_rendersamples
        )
        render_props.parm("enabledof").set(0)
        render_props.parm("enablemblur").set(0)

        rop = net.createNode("usdrender_rop")
        rop.parm("renderer").set("BRAY_HdKarma")  # Karma CPU
        rop.setFirstInput(render_props)
        rop.parm("soho_foreground").set(1)
    except Exception:
        # Off the stack like the create above: a bare destroy is
        # itself undoable and hands the half-built scaffold back.
        with hou.undos.disabler():
            net.destroy()
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
    """Render one material into a pre-built scaffold, writing png_path.

    Creates and destroys ONLY the per-material nodes (the material
    library and the exr->png copnet); the scaffold's lopnet/reference/
    floor/render-properties/ROP persist for the next material.
    """
    net = scaffold["net"]
    lib1 = scaffold["lib1"]
    render_props = scaffold["render_props"]
    rop = scaffold["rop"]
    display = scaffold["display"]
    view = scaffold["view"]
    space = scaffold["space"]

    # Build path. UNIQUE per render (timestamp suffix): Houdini
    # caches images by file path, so a rerender writing to the same
    # intermediate EXR name could have its EXR->PNG conversion
    # served the PREVIOUS render's cached pixels - a fresh-looking
    # PNG with stale content, which is exactly what rerender/
    # overwrite produced (a stale leftover EXR from an interrupted
    # run causes the same). A never-reused name defeats both.
    # Off the same composition as the PNG, so the intermediate and
    # the final image can never land in different directories.
    path = "%s.%d.acescg.exr" % (
        os.path.splitext(png_path)[0], int(time.time() * 1000))

    lib = None
    copnet = None
    try:
        # OFF THE UNDO STACK, like the scaffold that holds them.
        # build_karma_scaffold disables its create and its destroy
        # for the reason research.md - Undo records; these
        # per-material children were the half still landing on the
        # stack, so rendering a thumbnail put entries in front of
        # the artist's own last edit.
        with hou.undos.disabler():
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
        # Empty when the material is a builder subnet with zero
        # children - nothing to select, nothing to render.
        if curr_nodes:
            curr_nodes[0].setSelected(True)

        # The render-time __activate__/opacity patch that used to live
        # here is gone: the material engine (nodes.activate_shader_inputs)
        # activates every input RECURSIVELY at build time, so the saved
        # material is already correct - and this loop only ever reached
        # TOP-LEVEL nodes anyway (the images are nested), which is why
        # it never actually fixed anything. Materials built now (clean
        # translator / converter output) carry no __activate__ parms at
        # all.
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

        # One explicit material entry (same pattern the floor library
        # lib1 above already uses), not fillmaterials - auto-fill
        # created an entry per material-ish node in the copied network
        # (shader, displacement, collect...), and the extra entries'
        # prims never generate (they're all part of the ONE material),
        # producing a yellow "Ignoring missing explicit primitive:
        # /materials/<name>" node error per extra entry on every
        # single thumbnail render.
        if debug.is_on():
            debug.event(
                "thumb", "karma material content",
                asset_id=str(asset_id),
                ocio_display=scaffold.get("display"),
                ocio_view=scaffold.get("view"),
                # GUARDED, like the identical index 40 lines above
                # ("Empty when the material is a builder subnet
                # with zero children"). It was the one unguarded
                # index in the function, and it sits inside the
                # Debug-Mode block - so an empty copy raised
                # IndexError for developers and testers, who are
                # exactly the people running with Debug on, while
                # the same material rendered fine for everyone
                # else. A diagnosis aid must never change the
                # outcome (overview.md §4d).
                textures=(debug.texture_snapshot(curr_nodes[0])
                          if curr_nodes else None),
            )
        debug.event(
            "thumb", "karma material node chosen",
            asset_id=str(asset_id),
            mat_node=mat_node.name() if mat_node else None,
            mat_type=mat_node.type().name() if mat_node else None,
            candidates=[(n.name(), n.type().name()) for n in curr_nodes],
        )
        if mat_node is not None:
            lib.parm("materials").set(1)
            lib.parm("matnode1").set(mat_node.name())
            lib.parm("matpath1").set("/materials/" + mat_node.name())
        else:
            # No recognisable material node - fall back to auto-fill
            # rather than render nothing.
            lib.parm("fillmaterials").pressButton()
        lib.parm("assign1").set(1)
        lib.parm("geopath1").set("/shaderBallScene/geo/ball")

        render_props.parm("picture").set(path)
        render_props.setFirstInput(lib)

        with debug.timed("batch", "husk render (rop execute)",
                         asset_id=str(asset_id)):
            rop.parm("execute").pressButton()

        if not os.path.exists(path):
            # The render produced nothing - fail loudly instead of
            # letting the conversion step write a PNG from stale
            # data (the old PNG stays, honestly old).
            debug.event(
                "thumb", "karma render produced no EXR",
                asset_id=str(asset_id), expected=path,
                rop=rop.path(),
                rop_errors=helpers.node_errors(rop),
                lib_errors=helpers.node_errors(lib),
            )
            debug.note("Karma thumbnail render produced no EXR "
                       "for " + str(asset_id) + " - keeping the old thumbnail")
            return False

        if hostver.has_new_cops():
            # Copnet Setup. OFF THE STACK, like the destroy in the
            # finally below and like the materiallibrary above:
            # created unconditionally and destroyed unconditionally
            # makes this staging, and staging with one half guarded
            # is the pair that comes back on a Ctrl+Z carrying its
            # children (practice.md > STAGING DESTROYS IN A
            # FINALLY). It was the last unguarded create in the
            # per-material path.
            with hou.undos.disabler():
                copnet = net.createNode("copnet")
            copnet.setName("exr_to_png", unique_name=True)

            cop_file = copnet.createNode("file")

            cop_file.parm("filename").set(path)
            cop_file.parm("aovs").set(1)
            cop_file.parm("aov1").set("C")
            cop_out = copnet.createNode("rop_image")
            cop_out.parm("trange").set(0)

            cop_out.setInput(0, cop_file)
            cop_out.parm("colorconversion").set(1)  # Set to Bake OpenColorIO
            cop_out.parm("ociodisplay").set(display)
            cop_out.parm("ocioview").set(view)

            cop_out.parm("copoutput").set(png_path)
            with debug.timed("batch", "exr->png conversion",
                             asset_id=str(asset_id)):
                cop_out.parm("execute").pressButton()

        else:  # Use Old COPs with restricted OCIO Capabilities
            # Copnet Setup - off the stack, same pair rule as the
            # H22 branch above.
            with hou.undos.disabler():
                copnet = net.createNode("cop2net")
            copnet.setName("exr_to_png", unique_name=True)

            cop_file = copnet.createNode("file")
            cop_file.parm("nodename").set(0)
            cop_file.parm("filename1").set(path)
            cop_file.parm("colorspace").set(3)  # Set to OpenColorIO
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
        # Destroy ONLY the per-material nodes so the scaffold is
        # clean for the next material (single-shot then destroys the
        # whole net anyway). Runs on interrupt too - no orphaned
        # material lib / copnet left behind.
        with hou.undos.disabler():
            if copnet is not None:
                copnet.destroy()
            if lib is not None:
                lib.destroy()
        # INSIDE the finally. It used to sit after it, so any
        # exception - notably hou.OperationInterrupted from ESC,
        # which create_thumbnail explicitly enables - propagated
        # through and skipped the removal. The names are
        # timestamp-unique by design, so nothing ever reclaimed
        # them: every interrupted render left a
        # <id>.<ms>.acescg.exr in the LIBRARY's image directory,
        # permanently.
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as exc:
                # A held intermediate (sync client, viewer) must
                # not fail the render.
                debug.event("thumb", "intermediate not removed",
                            path=path, error=str(exc))

    # Measure the PNG that was actually written. A report that a tile
    # looks black is ambiguous at that size - an all-zero render, a
    # transparent image and a stale file are different bugs, and this
    # tells them apart without another round-trip.
    if debug.is_on():
        debug.event("thumb", "karma thumbnail written",
                    asset_id=str(asset_id), **debug.image_stats(png_path))

    # THE OUTPUT IS CHECKED, not assumed. The EXR is verified above and
    # then the conversion runs; this function returned True regardless
    # of whether the PNG appeared, so a copnet that would not cook, an
    # unwritable `img/` or a rejected OCIO string read as success. A
    # failed render keeps the OLD thumbnail, so the tile shows the
    # previous image and nothing anywhere said the new one never
    # happened - the same reason `thumbs._rendered` exists for the
    # other three renderers. The measurement above cannot do this job:
    # it only runs under Debug Mode.
    if not os.path.exists(png_path) or os.path.getsize(png_path) == 0:
        debug.event("thumb", "karma produced no PNG",
                    asset_id=str(asset_id), path=png_path)
        return False

    return True
