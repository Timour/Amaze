"""The USD preview scene, Karma's and Octane's: one stage per batch, written for husk to render."""
import datetime
import os

import hou

import amaze
from amaze.core import debug
from amaze.helpers import helpers, hostver
from amaze.preview import thumbnail_scene

RENDER_CAMERA = "/shaderBallScene/cameras/RenderCam"
BALL = "/shaderBallScene/geo/ball"    # the prim every thumbnail material is bound to
BATCH_MATERIAL = "/materials/amaze_thumb_%d"    # one per material in a batch's stage
FLOOR_TEXTURE = {    # Octane reads no `.rat`; the EXR is the same picture ▸r/octane-thumbnail
    "Karma": "$AMAZE/scripts/python/amaze/res/img/FloorTexture.rat",
    "Octane": "$AMAZE/scripts/python/amaze/res/img/FloorTexture.exr",
}
OCTANE_LOP_CONTAINER = "octane_solaris_material_builder"    # wired at creation ▸r/octane-builder
COPIED_WHOLE = ("subnet", OCTANE_LOP_CONTAINER)    # containers a material library takes as they are


def _karma_settings(net, preferences) -> tuple:
    """Karma CPU's render properties and ROP: (settings, rop); husk's `-o` names the picture."""
    render_props = net.createNode("karmarenderproperties")
    render_props.parm("camera").set(RENDER_CAMERA)
    render_props.parm("res_mode").set("manual")
    render_props.parm("res_mode").pressButton()
    render_props.parm("resolutionx").set(preferences.rendersize)
    render_props.parm("resolutiony").deleteAllKeyframes()
    render_props.parm("resolutiony").set(preferences.rendersize)
    render_props.parm("engine").set("cpu")    # CPU, not XPU ▸r/karma-thumbnail-cost
    render_props.parm("engine").pressButton()
    render_props.parm("samplesperpixel").set(    # the CPU dial; `pathtracedsamples` is XPU's
        preferences.karma_rendersamples)
    render_props.parm("enabledof").set(0)
    render_props.parm("enablemblur").set(0)

    rop = net.createNode("usdrender_rop")
    rop.parm("renderer").set("BRAY_HdKarma")    # Karma CPU
    rop.setFirstInput(render_props)
    rop.parm("soho_foreground").set(1)
    return render_props, rop


OCTANE_SETTINGS = "otoy::Octane"    # Octane's render settings LOP ▸r/octane-thumbnail
OCTANE_PATH_TRACING_CAP = "xn__octaneglobalmaxsamples4_jebg"    # `maxsamples4` here, not 3


def _octane_settings(net, preferences) -> tuple:
    """Octane's render settings and a USD Render ROP through its delegate, lit by the stage."""
    settings = net.createNode(OCTANE_SETTINGS)
    settings.parm("camera").set(RENDER_CAMERA)
    settings.parm("res_mode").set("manual")
    settings.parm("res_mode").pressButton()    # unlocks the height, as Karma's does
    for name in ("resolution1", "resolution2"):
        settings.parm(name).deleteAllKeyframes()
        settings.parm(name).set(preferences.rendersize)
    settings.parm("xn__octaneglobalParmKernel_wcbg").set("NT_KERN_PATHTRACING")
    settings.parm("xn__octaneglobalParmEnvironment_1kbg").set("NONE")    # the stage's own lights
    settings.parm(OCTANE_PATH_TRACING_CAP).set(preferences.octane_rendersamples)
    settings.parm("xn__octaneglobalociocolorspace_fjbg").set("ACEScg")    # as Karma's EXR

    rop = net.createNode("usdrender_rop")
    rop.parm("renderer").set("HdOctaneRendererPlugin")
    rop.setFirstInput(settings)
    rop.parm("soho_foreground").set(1)
    return settings, rop


RENDER_SETTINGS = {"Karma": _karma_settings, "Octane": _octane_settings}

OCTANE_LIGHT_SCALE = 0.5    # Octane lights this stage about twice as bright ▸r/octane-thumbnail
OCTANE_STAGE_EDIT = (    # the camera's f-stop off, as Karma's settings turn DOF off; the lights scaled
    "from pxr import UsdLux\n"
    "stage = hou.pwd().editableStage()\n"
    "stage.GetPrimAtPath(%r).GetAttribute('fStop').Set(0.0)\n"
    "for prim in stage.Traverse():\n"
    "    if prim.HasAPI(UsdLux.LightAPI):\n"
    "        intensity = UsdLux.LightAPI(prim).GetIntensityAttr()\n"
    "        intensity.Set(intensity.Get() * %r)\n")


def _octane_stage(net, upstream):
    """The stage as Octane needs it, edited after `upstream`: no depth of field, lights scaled."""
    edit = net.createNode("pythonscript", "octane_stage")
    edit.parm("python").set(OCTANE_STAGE_EDIT % (RENDER_CAMERA, OCTANE_LIGHT_SCALE))
    edit.setFirstInput(upstream)
    return edit


def build_usd_scaffold(preferences, renderer="Karma"):
    """The thumbnail stage for `renderer`, built once; None with no Scene Viewer to read OCIO from."""
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
            lib1.setFirstInput(
                _octane_stage(net, ref) if renderer == "Octane" else ref)
            surf = lib1.createNode("mtlxstandard_surface")
            tex = lib1.createNode("mtlxtiledimage")
            tex.parm("file").set(FLOOR_TEXTURE[renderer])
            surf.setInput(1, tex, 0)
            surf.setGenericFlag(hou.nodeFlag.Material, True)
            lib1.parm("materials").set(1)
            lib1.parm("matnode1").set("mtlxstandard_surface1")
            lib1.parm("matpath1").set("/thumb/bg_material")
            lib1.parm("geopath1").set("/shaderBallScene/geo/plane/mesh_0")
            lib1.parm("assign1").set(1)

            render_props, rop = RENDER_SETTINGS[renderer](net, preferences)
        except Exception:
            net.destroy()    # a half-built scaffold is never handed back, and the destroy is under the same disabler as the create
            raise
    return {
        "renderer": renderer,
        "net": net,
        "lib1": lib1,
        "render_props": render_props,
        "rop": rop,
        "display": display,
        "view": view,
        "space": space,
    }


def _stage_material(lib, node, asset_id, prim_path: str) -> str:
    """One material copied into `lib` as its one entry at `prim_path`; the path, "" with none."""
    curr_items = node
    if not isinstance(node, list):
        if curr_items.type().name() in COPIED_WHOLE:
            curr_items = (node,)
        elif "mtlxopen_pbr_surface" in curr_items.type().name():
            curr_items = (node,)
        else:
            curr_items = node.children()

    with debug.timed("batch", "copy nodes into lib", asset_id=str(asset_id)):
        if not isinstance(node, list) and node.type().name() == "octane_vopnet":
            from amaze.render.material_conversion import octane    # late: it imports render/
            curr_nodes = [octane.classic_into(lib, node)]
        else:
            curr_nodes = hou.copyNodesTo(curr_items, lib)  # type: ignore
    if curr_nodes:    # empty for a builder subnet with no children: nothing to render
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
            elif ("subnet" in n.type().name()
                  or n.type().name() == OCTANE_LOP_CONTAINER):
                n.setGenericFlag(hou.nodeFlag.Material, True)
                mat_node = n
                break

    if debug.is_on():
        debug.event(
            "thumb", "karma material content",
            asset_id=str(asset_id),
            textures=(texture_snapshot(curr_nodes[0])
                      if curr_nodes else None),    # guarded: a diagnosis aid never changes the outcome
        )
    debug.event(
        "thumb", "karma material node chosen",
        asset_id=str(asset_id),
        mat_node=mat_node.name() if mat_node else None,
        mat_type=mat_node.type().name() if mat_node else None,
        candidates=[(n.name(), n.type().name()) for n in curr_nodes],
    )
    if mat_node is not None:
        lib.parm("materials").set(1)    # ONE entry: auto-fill's extra entries never generate
        lib.parm("matnode1").set(mat_node.name())
        lib.parm("matpath1").set(prim_path)
    else:
        lib.parm("fillmaterials").pressButton()    # no recognisable material node: auto-fill
    lib.parm("assign1").set(0)    # husk binds each frame's material itself ▸r/husk-startup
    if not lib.parm("materials").evalAsInt():
        return ""
    return lib.parm("matpath1").evalAsString()


def write_batch(scaffold, items, out_dir: str) -> dict:
    """Every (asset_id, node) into ONE USD file for husk, a material prim each. ▸r/husk-startup"""
    net = scaffold["net"]
    render_props = scaffold["render_props"]
    rop = scaffold["rop"]
    libs = []
    prims = []
    with helpers.preserving_selection_and_current():    # copyNodesTo clears it ▸r/node-graph
        with hou.undos.disabler():    # every node operation is an undo entry ▸r/undo-groups
            try:
                upstream = scaffold["lib1"]
                for i, (asset_id, node) in enumerate(items):
                    lib = net.createNode("materiallibrary")
                    lib.setFirstInput(upstream)
                    libs.append(lib)
                    prims.append(_stage_material(lib, node, asset_id, BATCH_MATERIAL % i))
                    upstream = lib
                render_props.setFirstInput(upstream)
                rop.parm("runcommand").set(0)    # the caller starts husk, in the background
                rop.parm("savetodirectory_directory").set(out_dir)
                with debug.timed("batch", "write batch usd", materials=len(items)):
                    rop.render()
            finally:
                render_props.setFirstInput(scaffold["lib1"])
                for lib in reversed(libs):
                    lib.destroy()
    return {
        "usd": os.path.join(out_dir, rop.parm("lopoutput").evalAsString()),
        "prims": prims,
        "ball": BALL,
        "renderer": scaffold["renderer"],
        "ocio": (scaffold["display"], scaffold["view"], scaffold["space"]),
    }


def exr_to_png(exr_path: str, png_path: str, ocio, asset_id: str = "") -> bool:
    """husk's ACEScg EXR as the tile's PNG, through the viewer's OCIO display and view."""
    display, view, space = ocio
    copnet = None
    with hou.undos.disabler():    # a create/destroy pair on the live stack returns on Ctrl+Z
        try:
            if hostver.has_new_cops():
                copnet = hou.node("/obj").createNode("copnet")
                copnet.setName("amaze_exr_to_png", unique_name=True)
                cop_file = copnet.createNode("file")
                cop_file.parm("filename").set(exr_path)
                cop_file.parm("aovs").set(1)
                cop_file.parm("aov1").set("C")
                cop_out = copnet.createNode("rop_image")
                cop_out.parm("trange").set(0)
                cop_out.setInput(0, cop_file)
                cop_out.parm("colorconversion").set(1)    # Bake OpenColorIO
                cop_out.parm("ociodisplay").set(display)
                cop_out.parm("ocioview").set(view)
                cop_out.parm("copoutput").set(png_path)
                with debug.timed("batch", "exr->png conversion", asset_id=str(asset_id)):
                    cop_out.parm("execute").pressButton()
            else:
                copnet = hou.node("/obj").createNode("cop2net")    # the old COPs
                copnet.setName("amaze_exr_to_png", unique_name=True)
                cop_file = copnet.createNode("file")
                cop_file.parm("nodename").set(0)
                cop_file.parm("filename1").set(exr_path)
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
            if copnet is not None:
                copnet.destroy()

    if debug.is_on():
        debug.event("thumb", "karma thumbnail written",    # a black, empty or stale PNG look alike
                    asset_id=str(asset_id), **image_stats(png_path))
    if not os.path.exists(png_path) or os.path.getsize(png_path) == 0:
        debug.event("thumb", "karma produced no PNG",    # checked, never assumed: the old one stays
                    asset_id=str(asset_id), path=png_path)
        return False
    return True


def image_stats(path: str) -> dict:
    """A rendered image measured, so a black-looking tile reads as all black, transparent or content."""
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


def texture_snapshot(root) -> list:
    """Every file reference under a network and whether it resolves; a missing one renders black."""
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
