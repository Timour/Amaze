"""
Generates a Thumbnail Scene and allows for Rendering Material Preview
"""

import hou
from amaze.core import debug
from amaze.preview import shaderball_scene

# (module reloads consolidated into panel.py's single chain)


def safe_set(node: hou.Node, parm_name: str, value, **kwargs) -> None:
    """Set a parm if it exists; skip silently if the renderer
    version does not expose it (parameter names change between
    Redshift releases)."""
    parm = node.parm(parm_name)
    if parm is None:
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path()
        )
        return
    try:
        parm.set(value, **kwargs)
    except (hou.Error, TypeError) as e:
        # hou.Error, not hou.OperationFailed: a renderer version that
        # changed a parm's TYPE (scalar <-> tuple) raises hou.InvalidSize,
        # which is a SIBLING of OperationFailed, not a subclass - it would
        # have escaped the one helper whose entire job is surviving
        # renderer version differences. Same trap that aborted two
        # converter rounds (thin film, OpenPBR).
        debug.event(
            "thumb", "parm skipped", parm=parm_name, node=node.path(), error=str(e)
        )


def ocio_from_viewer():
    """The Scene Viewer's OCIO display, view and working space, or None.

    ONE lookup for both callers. `karma_scene.build_karma_scaffold` had a
    second copy that differed only in the fallback spelling of the
    working space, and a lookup written twice is one that drifts
    (practice.md > A LOOKUP WRITTEN FOUR TIMES).

    `hou.ui` DOES NOT EXIST under hython, and asking for it there raised
    AttributeError rather than reporting "no viewer" - which is why the
    Redshift scene test could never run headless. Absent GUI and absent
    viewer are the same answer to the caller: there is nowhere to read a
    display and view from.

    It is also the SEAM the tests replace, so the parts of a scene build
    that need no GUI can be exercised without one.
    """
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
    """
    Generates a Thumbnail Scene and allows for Rendering Material Preview
    """

    def __init__(self, renderer: str):
        # No default. It used to be "Mantra", which meant a caller that
        # forgot the argument silently built a scene for a renderer
        # instead of failing - and the door's own docstring has always
        # written it as ThumbNailScene(renderer), with no default.
        self.renderer = renderer

        # Checked BEFORE anything is created in the scene: raising after
        # the subnet existed leaked an orphan /obj/subnet1 per attempt.
        ocio = ocio_from_viewer()
        if not ocio:
            # __init__ can only return None, so a bare "return False" here
            # (the old behaviour) raised a TypeError instead of failing
            # gracefully. Raise a clear error so callers can report it.
            raise RuntimeError(
                "Amaze: no Scene Viewer pane is open - cannot build a "
                "thumbnail scene. Open a Scene Viewer and try again."
            )

        # THE USER'S SELECTION, CAPTURED BEFORE ANYTHING IS CREATED.
        # `createNode` selects what it creates, so the Redshift branch's
        # own save-and-restore read a selection this build had already
        # replaced - it put back the scene's null instead of the user's
        # nodes. The restore was written and has been wrong since;
        # nothing noticed because its test could not run headless.
        self._user_selection = hou.selectedNodes()

        # Render Independemt Setup
        self.geo_node = hou.node("/obj").createNode("subnet")

        # EVERYTHING BELOW CAN RAISE, and the subnet already exists.
        # The viewer check above was moved before createNode for exactly
        # this reason and then only that one case was covered: a renamed
        # light type on a new Redshift build, or an Octane render target
        # whose ::2.x branch matches nothing (leaving target.parm(...)
        # None), raises from build_lights/build_rops - and the callers
        # catch it, report "thumbnail failed, material saved without
        # one", and leave /obj/Thumbnail_Octane1, 2, 3... in the user's
        # scene, one per save attempt, each carrying a live ROP.
        try:
            self.display = ocio["display"]
            self.view = ocio["view"]
            # `space` is deliberately not kept. The working space was
            # read only by the old cop2net bake, which was Mantra's;
            # karma_scene reads its own from ocio_from_viewer().

            self.build_parm_templates()

            self.geo_node.parm("path").set(
                "$HIP/render/$HIPNAME.$OS.$F4.exr")
            self.geo_node.parm("resx").set(512)
            self.geo_node.parm("resy").set(512)
            self.geo_node.parm("lights").set("*")

            # ONE BODY FOR BOTH RENDERERS. It was three branches, one
            # per renderer, character-identical except that Mantra
            # executed through `self.comp` - the extra ROP its own
            # EXR->PNG bake needed. With Mantra gone the remaining two
            # were the same body twice, so the branch is only about
            # which renderers this scene serves at all.
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
            # Take the half-built scene with us. The caller still sees
            # the original exception - this only stops it costing the
            # user a node tree they never asked for.
            try:
                self.geo_node.destroy()
            except Exception:                                # noqa: BLE001
                pass
            raise

    def build_parm_templates(self) -> None:
        """
        Build ParmTemplate for Population of Parameters
        """
        # Add Parms on top
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

        data_template = hou.ButtonParmTemplate("render", "Render", script_callback=None)
        self.geo_node.addSpareParmTuple(data_template)

    def build_scene(self) -> None:
        """
        Build the entire Scene with Lights, Camera and Rops
        """
        self.ropnet = self.geo_node.createNode("ropnet")

        self.build_lights()
        self.build_cam()
        self.build_rops()

        self.geo_node.layoutChildren()

    def build_lights(self) -> None:
        """
        Build Lights for the set Renderer
        """
        if "Redshift" in self.renderer:
            # Lights
            self.lgt_right = self.geo_node.createNode("rslight")
            self.lgt_right.setName("Right")
            self.lgt_env = self.geo_node.createNode("rslightdome::2.0")
            self.lgt_env.setName("Env")
            self.lgt_left = self.geo_node.createNode("rslight")
            self.lgt_left.setName("Left")

            # Right
            safe_set(self.lgt_right, "tx", 0.182989)
            safe_set(self.lgt_right, "ty", 0.400678)
            safe_set(self.lgt_right, "tz", -0.637707)
            safe_set(self.lgt_right, "rx", -164.722)
            safe_set(self.lgt_right, "ry", -11.677)
            safe_set(self.lgt_right, "rz", 0)
            safe_set(self.lgt_right, "RSL_intensityMultiplier", 2)
            safe_set(self.lgt_right, "Light1_exposure", 1.5)
            safe_set(self.lgt_right, "areasize1", 0.5)
            safe_set(self.lgt_right, "areasize2", 0.5)
            safe_set(self.lgt_right, "areasize3", 0.5)
            safe_set(self.lgt_right, "RSL_samples", 128)
            safe_set(self.lgt_right, "RSL_cameraScale", 0)
            # Left
            safe_set(self.lgt_left, "tx", 0.00626206)
            safe_set(self.lgt_left, "ty", 0.290401)
            safe_set(self.lgt_left, "tz", 0.562686)
            safe_set(self.lgt_left, "rx", 0)
            safe_set(self.lgt_left, "ry", 0)
            safe_set(self.lgt_left, "rz", 0)
            safe_set(self.lgt_left, "RSL_intensityMultiplier", 7.1)
            safe_set(self.lgt_left, "Light1_exposure", 0)
            safe_set(self.lgt_left, "areasize1", 0.28)
            safe_set(self.lgt_left, "areasize2", 0.5)
            safe_set(self.lgt_left, "areasize3", 0.5)
            safe_set(self.lgt_left, "RSL_samples", 128)
            safe_set(self.lgt_left, "RSL_cameraScale", 0)
            # DomeLight
            safe_set(self.lgt_env, "light_intensity", 0.3)
            safe_set(self.lgt_env, "ry", 17.6)
            safe_set(
                self.lgt_env, "env_map",
                "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"
            )
        elif "Octane" in self.renderer:
            # Lights

            self.lgt_right = self.geo_node.createNode("octane_light")
            self.lgt_right.setName("Right")
            self.lgt_left = self.geo_node.createNode("octane_light")
            self.lgt_left.setName("Left")

            # Octane Version Madness!
            if self.lgt_right.parm("blackbody_efficiency_color_A_VALUEr"):
                safe_set(self.lgt_right, "blackbody_efficiency_color_A_VALUEr", 1)
                safe_set(self.lgt_right, "blackbody_efficiency_color_A_VALUEg", 1)
                safe_set(self.lgt_right, "blackbody_efficiency_color_A_VALUEb", 1)
                safe_set(self.lgt_left, "blackbody_efficiency_color_A_VALUEr", 1)
                safe_set(self.lgt_left, "blackbody_efficiency_color_A_VALUEg", 1)
                safe_set(self.lgt_left, "blackbody_efficiency_color_A_VALUEb", 1)
            # Right
            safe_set(self.lgt_right, "tx", 0.182989)
            safe_set(self.lgt_right, "ty", 0.400678)
            safe_set(self.lgt_right, "tz", -0.637707)
            safe_set(self.lgt_right, "rx", -164.722)
            safe_set(self.lgt_right, "ry", -11.677)
            safe_set(self.lgt_right, "rz", 0)
            safe_set(self.lgt_right, "sx", 0.5)
            safe_set(self.lgt_right, "sy", 0.5)
            safe_set(self.lgt_right, "sz", 0.5)
            safe_set(self.lgt_right, "NT_EMIS_BLACKBODY1_power", 30)
            # Left
            safe_set(self.lgt_left, "tx", -0.0788468)
            safe_set(self.lgt_left, "ty", 0.247556)
            safe_set(self.lgt_left, "tz", 0.562686)
            safe_set(self.lgt_left, "sx", 0.28)
            safe_set(self.lgt_left, "sy", 0.5)
            safe_set(self.lgt_left, "sz", 0.5)
            safe_set(self.lgt_left, "NT_EMIS_BLACKBODY1_power", 15)
            # Do weird Octane Domelight as shader
            self.mat_net = self.geo_node.createNode("matnet")

            # Octane Current
            target = self.mat_net.createNode("octane_mat_renderTarget")

            if "::2.0" in target.type().name():
                # Octane FUTURE
                safe_set(target, "kernelMenu", 3)
                safe_set(target, "environmentMenu", 6)
                safe_set(target, "maxsamples", 200)
                safe_set(target, "textureEnvPower", 0.2)
                safe_set(
                    target, "textureEnvironmentFilename",
                    "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"
                )
                safe_set(target, "colorSpace", "NAMED_COLOR_SPACE_ACESCG")
                target.setName("Octane_RenderTarget")
            elif "::2.2" in target.type().name():
                # Octane 2026
                safe_set(target, "kernelMenu", 3)
                safe_set(target, "environmentMenu", 6)
                safe_set(target, "maxsamples", 200)
                safe_set(target, "textureEnvPower_1", 0.2)
                safe_set(
                    target, "textureEnvFilename_1",
                    "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"
                )
                safe_set(target, "textureEnvColorSpace_1", "NAMED_COLOR_SPACE_ACESCG")
                target.setName("Octane_RenderTarget")
            elif "::2.1" in target.type().name():
                # Octane 2025
                safe_set(target, "kernelMenu", 3)
                safe_set(target, "environmentMenu", 6)
                safe_set(target, "maxsamples", 200)
                safe_set(target, "textureEnvPower", 0.2)
                safe_set(
                    target, "textureEnvironmentFilename",
                    "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"
                )
                safe_set(target, "colorSpace", "NAMED_COLOR_SPACE_ACESCG")
                target.setName("Octane_RenderTarget")

            else:
                # Octane Current
                safe_set(target, "parmKernel", 1)
                safe_set(target, "parmEnvironment", 1)
                safe_set(target, "maxSamples2", 200)
                safe_set(target, "power4", 0.2)
                safe_set(
                    target, "A_FILENAME4",
                    "$AMAZE/scripts/python/amaze/res/img/photo_studio_01_4k_ACEScg.hdr"
                )
                safe_set(target, "colorSpace2", "NAMED_COLOR_SPACE_ACESCG")
            target.setName("Octane_RenderTarget")

    def build_cam(self) -> None:
        """
        Build Camera for the set Renderer
        """
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

        # Rot cam to match shaderball
        null = self.geo_node.createNode("null")
        safe_set(self.cam, "keeppos", 1)
        self.cam.setInput(0, null, 0)
        safe_set(null, "ry", 180)
        # The (only) shaderball's camera framing - these were the
        # Simple scene's adjustments while two scenes existed.
        safe_set(null, "ry", 170)
        safe_set(null, "ty", -0.01)
        safe_set(null, "scale", 1.1)
        if "Redshift" in self.renderer:
            # The spare-parameter hscript works on the SELECTION, so
            # the user's own node selection is set aside and put back:
            # building a thumbnail scene must not eat what they had
            # selected in the network editor.
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
        """
        Build Rops for the set Renderer
        """

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

            safe_set(self.rop, "RS_objects_exclude", self.geo_node.parm("obj_exclude"))
            safe_set(self.rop, "RS_lights_candidate", self.geo_node.parm("lights"))
            safe_set(
                self.rop,
                "RS_outputFileNamePrefix",
                self.geo_node.parm("path"),
                follow_parm_reference=False,
            )

        if "Octane" in self.renderer:
            # RopNet Setup
            self.rop = self.ropnet.createNode("Octane_ROP")

            # Guarded like the Redshift ROP above: parm names on Octane_ROP
            # have already been observed to shift between versions (see the
            # "Octane Version Madness!" light setup), so a rename here
            # should degrade gracefully instead of crashing the render.
            safe_set(self.rop, "HO_renderCamera", "../../RenderCam")
            # safe_set(self.rop, "HO_iprCamera", "../../RenderCam")
            safe_set(self.rop, "HO_renderTarget", "../../matnet1/Octane_RenderTarget")

            safe_set(self.rop, "HO_renderToMPlay", 0)

            safe_set(self.rop, "HO_img_colorSpace", 5)
            safe_set(self.rop, "HO_img_ocioColorSpace", 114)

            safe_set(self.rop, "HO_img_fileFormat", 0)

            safe_set(self.rop, "HO_mbDeformations", 0)
            safe_set(self.rop, "HO_mbFur", 0)
            safe_set(self.rop, "HO_mbInstances", 0)
            safe_set(self.rop, "HO_mbParticles", 0)

            safe_set(self.rop, "HO_img_deepFile", "deep filename")

            safe_set(self.rop, "HO_objects_exclude", self.geo_node.parm("obj_exclude"))

            safe_set(
                self.rop,
                "HO_img_fileName",
                self.geo_node.parm("path"),
                follow_parm_reference=False,
            )

    def get_node(self) -> hou.Node:
        """
        Get the currently attached GeoNode
        """
        return self.geo_node
