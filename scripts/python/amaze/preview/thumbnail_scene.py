"""The room a material thumbnail renders in: lights, camera, output."""

import hou
from amaze.core import debug
from amaze.preview import shaderball_scene

ENV_MAP = "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"

RIGHT_TRANSLATE = (0.182989, 0.400678, -0.637707)
RIGHT_ROTATE = (-164.722, -11.677, 0)
RIGHT_SIZE = (0.5, 0.5, 0.5)
LEFT_TRANSLATE = {"Redshift": (0.00626206, 0.290401, 0.562686),
                  "Octane": (-0.0788468, 0.247556, 0.562686)}
LEFT_ROTATE = (0, 0, 0)
LEFT_SIZE = (0.28, 0.5, 0.5)

SIZE_PARMS = {"Redshift": ("areasize1", "areasize2", "areasize3"),
              "Octane": ("sx", "sy", "sz")}


def safe_set(node: hou.Node, parm_name: str, value, **kwargs) -> None:
    """Set a parm, skipping one this renderer version does not expose; catches `hou.Error`, since `InvalidSize` is a sibling of `OperationFailed`, not a subclass. ▸r/hou-errors"""
    parm = node.parm(parm_name)
    if parm is None:
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path()
        )
        return
    try:
        parm.set(value, **kwargs)
    except (hou.Error, TypeError) as e:
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path(),
            error=str(e)
        )


def rig_key(renderer: str) -> str:
    """Which light-rig spelling `renderer` uses; raises rather than silently placing nothing."""
    for key in SIZE_PARMS:
        if key in renderer:
            return key
    raise hou.OperationFailed(
        "Amaze: no thumbnail light rig for renderer %r" % renderer)


def place_light(node: hou.Node, renderer: str, translate, rotate,
                size) -> None:
    """Position, rotate and size one key light, in this renderer's own size-parm spelling; `rotate` None leaves rotation untouched."""
    for parm_name, value in zip(("tx", "ty", "tz"), translate):
        safe_set(node, parm_name, value)
    if rotate is not None:
        for parm_name, value in zip(("rx", "ry", "rz"), rotate):
            safe_set(node, parm_name, value)
    for parm_name, value in zip(SIZE_PARMS[rig_key(renderer)], size):
        safe_set(node, parm_name, value)


def ocio_from_viewer():
    """The Scene Viewer's OCIO display, view and working space, or None when there is no GUI or no viewer - the seam the tests replace."""
    ui = getattr(hou, "ui", None)
    if ui is None:
        return None
    viewer = ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
    if not viewer:
        return None
    space = "ACEScg"
    for candidate in hou.Color.ocio_spaces():
        if "acescg" in candidate.lower():
            space = candidate
            break
    return {
        "display": viewer.getOCIODisplay(),
        "view": viewer.getOCIOView(),
        "space": space,
    }


class ThumbNailScene:
    """One material-preview scene, built per renderer, used once, destroyed by the caller."""

    def __init__(self, renderer: str):
        # No default renderer: a forgotten argument would silently pick one.
        self.renderer = renderer

        ocio = ocio_from_viewer()
        if not ocio:
            raise RuntimeError(
                "Amaze: no Scene Viewer pane is open - cannot build a "
                "thumbnail scene. Open a Scene Viewer and try again."
            )

        self._user_selection = hou.selectedNodes()

        self.geo_node = hou.node("/obj").createNode("subnet")

        try:
            self.display = ocio["display"]
            self.view = ocio["view"]

            self.build_parm_templates()

            self.geo_node.parm("path").set(
                "$HIP/render/$HIPNAME.$OS.$F4.exr")
            self.geo_node.parm("resx").set(512)
            self.geo_node.parm("resy").set(512)
            self.geo_node.parm("lights").set("*")

            if "Redshift" in renderer or "Octane" in renderer:
                self.shaderball = shaderball_scene.ShaderBallSetup(
                    self.renderer, self.geo_node
                )

                self.build_scene()
                self.shaderball.get_geo_node().parm("mat_ball").set(
                    self.geo_node.parm("mat")
                )
                self.rop.parm("execute").set(self.geo_node.parm("render"))
        except Exception:
            try:
                self.geo_node.destroy()
            except Exception:                                # noqa: BLE001
                pass
            raise

    def build_parm_templates(self) -> None:
        """Add the spare parms the caller drives this scene through."""
        name = "Thumbnail_" + self.renderer
        self.geo_node.setName(name, True)

        data_template = hou.StringParmTemplate(
            "mat",
            "ShaderBall Material",
            1,
            string_type=hou.stringParmType.NodeReference,
        )
        self.geo_node.addSpareParmTuple(data_template)

        data_template = hou.FloatParmTemplate("res", "Resolution", 2)
        self.geo_node.addSpareParmTuple(data_template)

        data_template = hou.StringParmTemplate(
            "obj_exclude",
            "Exclude Objects",
            1,
            string_type=hou.stringParmType.NodeReference,
        )
        self.geo_node.addSpareParmTuple(data_template)

        data_template = hou.StringParmTemplate(
            "lights",
            "Lights",
            1,
            string_type=hou.stringParmType.NodeReference,
        )
        self.geo_node.addSpareParmTuple(data_template)

        data_template = hou.StringParmTemplate(
            "path",
            "Render Path",
            1,
            string_type=hou.stringParmType.FileReference,
        )
        self.geo_node.addSpareParmTuple(data_template)

        data_template = hou.ButtonParmTemplate(
            "render", "Render", script_callback=None)
        self.geo_node.addSpareParmTuple(data_template)

    def build_scene(self) -> None:
        """Build the whole scene: lights, camera and ROPs."""
        self.ropnet = self.geo_node.createNode("ropnet")

        self.build_lights()
        self.build_cam()
        self.build_rops()

        self.geo_node.layoutChildren()

    def build_lights(self) -> None:
        """Build the two key lights and the environment for this renderer."""
        if "Redshift" in self.renderer:
            self.lgt_right = self.geo_node.createNode("rslight")
            self.lgt_right.setName("Right")
            self.lgt_env = self.geo_node.createNode("rslightdome::2.0")
            self.lgt_env.setName("Env")
            self.lgt_left = self.geo_node.createNode("rslight")
            self.lgt_left.setName("Left")

            place_light(self.lgt_right, self.renderer, RIGHT_TRANSLATE,
                        RIGHT_ROTATE, RIGHT_SIZE)
            safe_set(self.lgt_right, "RSL_intensityMultiplier", 2)
            safe_set(self.lgt_right, "Light1_exposure", 1.5)
            safe_set(self.lgt_right, "RSL_samples", 128)
            safe_set(self.lgt_right, "RSL_cameraScale", 0)

            place_light(self.lgt_left, self.renderer,
                        LEFT_TRANSLATE["Redshift"], LEFT_ROTATE, LEFT_SIZE)
            safe_set(self.lgt_left, "RSL_intensityMultiplier", 7.1)
            safe_set(self.lgt_left, "Light1_exposure", 0)
            safe_set(self.lgt_left, "RSL_samples", 128)
            safe_set(self.lgt_left, "RSL_cameraScale", 0)

            safe_set(self.lgt_env, "light_intensity", 0.3)
            safe_set(self.lgt_env, "ry", 17.6)
            safe_set(self.lgt_env, "env_map", ENV_MAP)
        elif "Octane" in self.renderer:
            self.lgt_right = self.geo_node.createNode("octane_light")
            self.lgt_right.setName("Right")
            self.lgt_left = self.geo_node.createNode("octane_light")
            self.lgt_left.setName("Left")

            if self.lgt_right.parm("blackbody_efficiency_color_A_VALUEr"):
                for light in (self.lgt_right, self.lgt_left):
                    for channel in "rgb":
                        safe_set(
                            light,
                            "blackbody_efficiency_color_A_VALUE" + channel,
                            1)

            place_light(self.lgt_right, self.renderer, RIGHT_TRANSLATE,
                        RIGHT_ROTATE, RIGHT_SIZE)
            safe_set(self.lgt_right, "NT_EMIS_BLACKBODY1_power", 30)

            place_light(self.lgt_left, self.renderer,
                        LEFT_TRANSLATE["Octane"], None, LEFT_SIZE)
            safe_set(self.lgt_left, "NT_EMIS_BLACKBODY1_power", 15)

            self.mat_net = self.geo_node.createNode("matnet")
            self.build_octane_environment()

    def build_octane_environment(self) -> None:
        """Octane's dome is a render-target shader, and its parm names move every version. ▸r/renderer-plugins"""
        target = self.mat_net.createNode("octane_mat_renderTarget")
        version = target.type().name()

        if "::2.2" in version:
            safe_set(target, "kernelMenu", 3)
            safe_set(target, "environmentMenu", 6)
            safe_set(target, "maxsamples", 200)
            safe_set(target, "textureEnvPower_1", 0.2)
            safe_set(target, "textureEnvFilename_1", ENV_MAP)
            safe_set(target, "textureEnvColorSpace_1",
                     "NAMED_COLOR_SPACE_ACESCG")
        elif "::2.0" in version or "::2.1" in version:
            safe_set(target, "kernelMenu", 3)
            safe_set(target, "environmentMenu", 6)
            safe_set(target, "maxsamples", 200)
            safe_set(target, "textureEnvPower", 0.2)
            safe_set(target, "textureEnvironmentFilename", ENV_MAP)
            safe_set(target, "colorSpace", "NAMED_COLOR_SPACE_ACESCG")
        else:
            safe_set(target, "parmKernel", 1)
            safe_set(target, "parmEnvironment", 1)
            safe_set(target, "maxSamples2", 200)
            safe_set(target, "power4", 0.2)
            safe_set(target, "A_FILENAME4", ENV_MAP)
            safe_set(target, "colorSpace2", "NAMED_COLOR_SPACE_ACESCG")

        target.setName("Octane_RenderTarget")

    def build_cam(self) -> None:
        """Build the render camera; the Redshift spare-parm hscript works on the SELECTION, so the user's is set aside and put back."""
        self.cam = self.geo_node.createNode("cam")

        safe_set(self.cam, "tx", 0.235797)
        safe_set(self.cam, "ty", 0.130498)
        safe_set(self.cam, "tz", 0.0811536)
        safe_set(self.cam, "rx", -12.578)
        safe_set(self.cam, "ry", 71.1787)
        safe_set(self.cam, "rz", 0)
        safe_set(self.cam, "aperture", 36)
        safe_set(self.cam, "near", 0.002)
        safe_set(self.cam, "far", 2000)
        safe_set(
            self.cam, "resx",
            self.geo_node.parm("resx"), follow_parm_reference=False
        )
        safe_set(
            self.cam, "resy",
            self.geo_node.parm("resy"), follow_parm_reference=False
        )
        safe_set(self.cam, "focus", 0.188163)
        safe_set(self.cam, "fstop", 1000)
        self.cam.setName("RenderCam", True)

        null = self.geo_node.createNode("null")
        safe_set(self.cam, "keeppos", 1)
        self.cam.setInput(0, null, 0)
        safe_set(null, "ry", 170)
        safe_set(null, "ty", -0.01)
        safe_set(null, "scale", 1.1)
        if "Redshift" in self.renderer:
            previous = self._user_selection
            try:
                self.cam.setSelected(True, True)
                try:
                    hou.hscript("Redshift_cameraSpareParameters -C 1")
                except hou.OperationFailed as e:
                    debug.event("thumb", "Redshift_cameraSpareParameters "
                                "unavailable - skipping", error=str(e))
                self.geo_node.setSelected(True, True)
            finally:
                try:
                    hou.clearAllSelected()
                    for node in previous:
                        node.setSelected(True)
                except hou.Error:
                    pass

    def build_rops(self) -> None:
        """Build the output ROP for this renderer, every parm through safe_set."""
        if "Redshift" in self.renderer:
            self.rop = self.ropnet.createNode("Redshift_ROP")
            safe_set(self.rop, "RS_renderCamera", "../../RenderCam")
            safe_set(self.rop, "RS_OCIOColorCorrection", 1)
            safe_set(self.rop, "RS_addDefaultLight", 1)
            safe_set(self.rop, "RS_outputFileFormat", 3)
            safe_set(self.rop, "RS_renderToMPlay", 0)
            safe_set(self.rop, "RS_nonBlockingRendering", 0)

            safe_set(self.rop, "RS_PFX_MPL_exposure", 0)
            safe_set(self.rop, "RS_PFX_MPL_effects", 0)
            safe_set(self.rop, "RS_PFX_HDR_exposure", 0)
            safe_set(self.rop, "RS_PFX_LDR_exposure", 0)

            safe_set(self.rop, "RS_objects_exclude",
                     self.geo_node.parm("obj_exclude"))
            safe_set(self.rop, "RS_lights_candidate",
                     self.geo_node.parm("lights"))
            safe_set(
                self.rop,
                "RS_outputFileNamePrefix",
                self.geo_node.parm("path"),
                follow_parm_reference=False,
            )

        if "Octane" in self.renderer:
            self.rop = self.ropnet.createNode("Octane_ROP")

            safe_set(self.rop, "HO_renderCamera", "../../RenderCam")
            safe_set(self.rop, "HO_renderTarget",
                     "../../matnet1/Octane_RenderTarget")

            safe_set(self.rop, "HO_renderToMPlay", 0)

            safe_set(self.rop, "HO_img_colorSpace", 5)
            safe_set(self.rop, "HO_img_ocioColorSpace", 114)

            safe_set(self.rop, "HO_img_fileFormat", 0)

            safe_set(self.rop, "HO_mbDeformations", 0)
            safe_set(self.rop, "HO_mbFur", 0)
            safe_set(self.rop, "HO_mbInstances", 0)
            safe_set(self.rop, "HO_mbParticles", 0)

            safe_set(self.rop, "HO_img_deepFile", "deep filename")

            safe_set(self.rop, "HO_objects_exclude",
                     self.geo_node.parm("obj_exclude"))

            safe_set(
                self.rop,
                "HO_img_fileName",
                self.geo_node.parm("path"),
                follow_parm_reference=False,
            )

    def get_node(self) -> hou.Node:
        """The subnet this scene was built into."""
        return self.geo_node
