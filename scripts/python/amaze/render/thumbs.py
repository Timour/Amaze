import contextlib
import os
import time
import hou

from amaze.core import debug
from amaze.core import material
import amaze
from amaze.core import tile_icons
from amaze.render import nodes
from amaze import preview
from amaze.prefs import prefs
from amaze.helpers import helpers, hostos

# (module reloads consolidated into panel.py's single chain)


class ThumbNailRenderer:
    def __init__(
        self, preferences: prefs.Prefs, mat: material.Material | None = None
    ) -> None:
        self._mat = mat
        self._preferences = preferences  # the caller's own Prefs, the authoritative in-memory copy, deliberately NOT reloaded here: a load() would discard unsaved edits and re-point the library at whatever settings.json names, which sends a test fixture's library back at the real one
        self._builder = None

    @staticmethod
    @contextlib.contextmanager
    def karma_batch(preferences):
        """Yield one Karma scaffold for a whole batch to share, or None when no Scene Viewer is open to take the OCIO display/view from - on a None every render in the batch simply builds and destroys its own. Pass what it yields to `create_thumbnail`."""
        scaffold = preview.build_karma_scaffold(preferences)  # the scaffold is a full USD stage composition - the expensive part of a Karma thumbnail, and identical for every material, so a batch pays the stage load once instead of N times
        try:
            yield scaffold
        finally:
            if scaffold is not None:
                with hou.undos.disabler():  # the create is already disabled inside build_karma_scaffold, and a bare destroy is the half that resurrects the whole scaffold on one Ctrl+Z
                    scaffold["net"].destroy()

    def create_thumbnail(self, scaffold=None) -> None:
        """Render this material's thumbnail; pass the scaffold from `karma_batch` when this render is one of a batch, or leave it None for a single render that builds and destroys its own."""
        node_handler = nodes.NodeHandler(self._preferences)
        if self._mat:
            ok, reason, _created = node_handler.import_asset_to_scene(
                self._mat, target="mat")  # target="mat", NOT "auto": "auto" resolves to whichever editor is ACTIVE, so a rerender with a LOP network in front imports into the user's materiallibrary, where register_in_materiallibrary appends an explicit entry that nothing removes when cleanup() destroys the node - leaving an entry naming a node that no longer exists, which is the `Ignoring missing explicit primitive` error on every cook from then on
            if not ok:  # the import refused - a missing, empty or unreadable material file, or a node type this session does not have - so there is no builder node and the render must not proceed
                if reason:
                    hou.ui.displayMessage(reason)  # type: ignore
                return

        try:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                if material.is_karma_renderer(self._mat.renderer):
                    if scaffold is not None:
                        preview.render_karma_into(  # the batch's scaffold is rendered into, never destroyed here - karma_batch owns both ends
                            scaffold, node_handler.builder_node,
                            self._mat.mat_id,
                            tile_icons.thumbnail_path(
                                self._preferences, self._mat.mat_id))
                    else:
                        self.create_thumb_mtlx(
                            node_handler.builder_node, self._mat.mat_id)
                elif self._mat.renderer == "Redshift":
                    self.create_thumb_redshift(node_handler.builder_node, self._mat.mat_id)
                elif self._mat.renderer == "Octane":
                    self.create_thumb_octane(node_handler.builder_node, self._mat.mat_id)

                else:
                    pass
        finally:
            node_handler.cleanup()  # in the finally, so an interrupted render (ESC) never leaves the imported material copy lingering in /mat

    def create_thumb_mtlx(self, node: hou.Node, asset_id: str) -> bool:
        """Single Karma thumbnail: build a throwaway scaffold, render one material into it, destroy it; False when no scaffold could be built. A whole batch shares ONE scaffold through `karma_batch` instead."""
        scaffold = preview.build_karma_scaffold(self._preferences)
        if scaffold is None:
            return False
        try:
            return preview.render_karma_into(
                scaffold, node, asset_id,
                tile_icons.thumbnail_path(self._preferences, asset_id))
        finally:
            with hou.undos.disabler():  # the create is disabled inside build_karma_scaffold, and a bare destroy is the half that resurrects the whole scaffold on one Ctrl+Z (the BOTH-ends rule below)
                scaffold["net"].destroy()  # in the finally, so an interrupted render leaves no orphaned lopnet with a live ROP in /obj

    @contextlib.contextmanager
    def _thumb_scene(self, renderer: str):
        """Yield (scene, thumb) and destroy the scene on every exit, the raising ones included - so set every parm INSIDE the `with`: anything that raises before it leaves a Thumbnail_* subnet behind in the user's scene, which is then saved into the hip file."""
        with hou.undos.disabler():  # research.md ▸ Undo names thumbnails explicitly; measured, a createNode/destroy pair on the live stack comes back on one Ctrl+Z and the same pair inside a disabler does not, so without this the next undo resurrects the throwaway scene
            sc = preview.ThumbNailScene(renderer)
            thumb = sc.get_node()
            try:
                yield sc, thumb
            finally:
                thumb.destroy()  # in the finally, so an interrupted render leaves no orphaned thumbnail scene with a live ROP in /obj

    def _setup_thumb_rop(self, thumb, node: hou.Node, out_path: str) -> None:
        """Set the shared material/path/exclusion/light/resolution parms on a thumbnail ROP, every one through `safe_set`, so a parm a given renderer build does not expose is skipped instead of raising."""
        preview.safe_set(thumb, "mat", node.path())
        preview.safe_set(thumb, "path", out_path)
        preview.safe_set(thumb, "obj_exclude", "* ^" + thumb.name())
        preview.safe_set(thumb, "lights", thumb.name() + "/*")
        preview.safe_set(thumb, "resx", self._preferences.rendersize)
        preview.safe_set(thumb, "resy", self._preferences.rendersize)

    def _rendered(self, png_path: str, renderer: str, asset_id: str,
                  errors=None) -> bool:
        """Did the render write png_path? False also logs it - callers must pass `errors` they gathered while the thumb scene was still alive, and must actually branch on the result (per practice.md #364 a failed render keeps the OLD thumbnail, so this log line is the only trace)."""
        if os.path.exists(png_path):
            return True
        debug.event("thumb", "render produced no image",
                    renderer=renderer, asset_id=str(asset_id),
                    path=png_path, errors=errors or "")  # gathered by the caller, not here: every caller reaches this AFTER its `with self._thumb_scene` block, which destroys the scene the ROP is a grandchild of, so reading them here raised hou.ObjectWasDeleted and node_errors swallowed it into {}
        return False

    @staticmethod
    def _pick_cop_thumb_source(temp: hou.Node) -> hou.Node | None:
        """FALLBACK-ONLY picker for assets saved before the source-node name was recorded at save time (that is the reliable path - see create_thumb_cop); shares the live pick's logic via helpers.pick_cop_display_child so the two cannot drift."""
        return helpers.pick_cop_display_child(temp)

    def create_thumb_geo_file(
        self, file_path: str, out_path: str, size: int
    ) -> bool:
        """Thumbnail for a geometry FILE: temp geo + the loader SOP for the extension, ortho camera fitted on the container-rotated bounding box, env light, rendered through the flipbook ROP (Karma CPU fallback) with the quadrant compensation; everything is destroyed in finally, and any failure returns False with an Amaze-prefixed console reason that callers must treat as "no thumbnail", never an error."""
        from amaze.core import geo_library  # lazy: geo_library imports this module at top level, so the import only works this way around; it owns the ONE extension->loader mapping
        loader_type = geo_library.loader_sop_for(file_path)

        base = os.path.basename(file_path)
        geo = None
        cam = None
        light = None
        rop = None
        try:
            with hou.undos.disabler():
                geo = hou.node("/obj").createNode("geo")
            try:
                loader = geo.createNode(loader_type)
            except hou.Error:
                debug.note("geometry thumbnail - no '%s' SOP available"
                    " for %s" % (loader_type, base))
                return False
            file_parm = helpers.find_file_parm(loader)
            if file_parm is None:
                debug.note("geometry thumbnail - no file parm on the "
                    + loader_type
                    + " SOP")
                return False
            file_parm.set(file_path)
            loader.setDisplayFlag(True)
            try:
                loader.setRenderFlag(True)
            except AttributeError:
                pass

            bbox = None
            try:
                geometry = loader.geometry()
                if geometry is not None:
                    bbox = geometry.boundingBox()
            except hou.Error:
                bbox = None
            if bbox is None or bbox.sizevec().length() == 0:
                debug.event("geo", "thumb failed", file=base,
                            reason="no cookable geometry")
                return False
            preview.safe_set(geo, "rx", -20.0)  # the 3/4 view comes from rotating the GEO CONTAINER, never the camera: the camera keeps its default orientation, which by Houdini's definition looks down -Z, and is only translated
            preview.safe_set(geo, "ry", 35.0)
            rot = hou.hmath.buildRotate(hou.Vector3(-20.0, 35.0, 0.0))  # the same rotation as the two container parms above, built by Houdini's own matrix builder, so the bbox corners below land where the geometry actually does

            with hou.undos.disabler():
                cam = hou.node("/obj").createNode("cam")
            preview.safe_set(cam, "resx", size)
            preview.safe_set(cam, "resy", size)
            min_vec = bbox.minvec()  # fit is axis-aligned in world space: the camera carries no rotation, so world x/y ARE the image axes
            max_vec = bbox.maxvec()
            world_min = None
            world_max = None
            for cx in (min_vec[0], max_vec[0]):
                for cy in (min_vec[1], max_vec[1]):
                    for cz in (min_vec[2], max_vec[2]):
                        corner = hou.Vector3(cx, cy, cz) * rot
                        if world_min is None:
                            world_min = hou.Vector3(corner)
                            world_max = hou.Vector3(corner)
                        else:
                            for axis in range(3):
                                world_min[axis] = min(world_min[axis], corner[axis])
                                world_max[axis] = max(world_max[axis], corner[axis])
            world_center = (world_min + world_max) * 0.5
            half_x = (world_max[0] - world_min[0]) * 0.5
            half_y = (world_max[1] - world_min[1]) * 0.5
            half_z = (world_max[2] - world_min[2]) * 0.5
            ortho_width = max(half_x, half_y, 0.0005) * 2.0 * 1.1  # fit: the larger world-space half-extent of the rotated bbox (floored, so a bbox flat in x and y cannot give a zero width), doubled to a full span, plus a 10% margin
            distance = half_z * 2.0 + ortho_width

            preview.safe_set(cam, "tx", world_center[0])
            preview.safe_set(cam, "ty", world_center[1])
            preview.safe_set(cam, "tz", world_center[2] + distance)  # placed straight in front of the rotated geometry on +Z - translation only, orientation stays identity
            preview.safe_set(cam, "projection", "ortho")  # ortho, not perspective: the identical fit math framed perfectly under Karma but far too tight under the Vulkan rasterizer, so the two read the perspective attributes (aperture/focal/aspect/res-override crop semantics) differently and that is not pinned down anywhere scriptable - ortho reduces framing to one number, orthowidth
            preview.safe_set(cam, "orthowidth", ortho_width)
            preview.safe_set(cam, "near", max(distance * 0.001, 0.00001))  # the Vulkan rasterizer honors near/far clip planes strictly where raytracers effectively do not, so both are scaled off the fitted distance and no model scale can clip
            preview.safe_set(cam, "far", distance + half_z * 4.0 + ortho_width)
            with hou.undos.disabler():
                light = hou.node("/obj").createNode("envlight")

            rop = None
            renderer_used = ""
            try:
                with hou.undos.disabler():
                    candidate = hou.node("/out").createNode("flipbook")  # flipbook, not opengl: per the H22 manual opengl is scheduled to be deleted and flipbook is its designated replacement - and flipbook renders with the VIEWPORT's configured renderer, so a viewport parked on a Karma delegate makes every thumbnail a viewport-quality Karma render
                if candidate.parm("camera") is not None:  # a flipbook with no camera parm is unusable here, so it is destroyed below and the Karma CPU fallback takes over
                    rop = candidate
                    renderer_used = "flipbook ROP (viewport renderer)"
                    preview.safe_set(cam, "orthowidth", ortho_width * 2.0)  # UNCONDITIONAL quadrant compensation, flipbook branch only: the capture is the LOWER-LEFT QUADRANT of a double-size framebuffer (visible span exactly half the set orthowidth, subject displaced up-right by a quarter frame), so doubling the width and shifting the centre up-right by half the INTENDED span makes the captured quadrant the intended frame - the doubling belongs to the capture, not to any Retina backing store (measured 2026-07-28: 255 thumbnails correct WITH it on Windows at device_pixel_ratio 1.0), so never gate it on device scale, and the Karma fallback renders the camera faithfully and must stay uncompensated
                    preview.safe_set(cam, "tx", world_center[0] + ortho_width * 0.5)  # half the INTENDED span, not the doubled one; if SideFX ever fixes the capture this overcorrects in the mirror signature - subject at half size, displaced down-left
                    preview.safe_set(cam, "ty", world_center[1] + ortho_width * 0.5)
                    preview.safe_set(rop, "vobjects", geo.path())  # scoped to OUR nodes: the flipbook ships vobjects=* / alights=*, which pulls the user's whole /obj scene and its lights into every thumbnail
                    preview.safe_set(rop, "alights", light.path())
                    shading = rop.parm("shadingmode")  # shading mode comes from Preferences (default: wire over shaded, plain shaded reads too flat), is set by menu token, and deliberately runs BEFORE the background block
                    wanted = getattr(
                        self._preferences,
                        "geometry_shading_mode",
                        "smoothwireshaded",
                    )
                    if shading is not None:
                        try:
                            menu_items = shading.parmTemplate().menuItems()  # resolve against the parm's OWN menu rather than guessing spellings: live testing had 'smoothwireshaded' rejected with the default landing on 'smooth', the real tokens being short forms ('smooth'/'smoothwire'/...), so the pref keeps its long descriptive value and this maps it onto whatever this build offers
                        except hou.Error:
                            menu_items = ()
                        resolved = wanted if wanted in menu_items else None

                        def _norm(token_string):
                            for junk in ("shaded", "frame", "line", "_"):
                                token_string = token_string.replace(junk, "")
                            return token_string

                        if resolved is None:
                            normalized = _norm(wanted)
                            for item in menu_items:
                                if _norm(item) == normalized:
                                    resolved = item
                                    break
                        if resolved is None:
                            normalized = _norm(wanted)
                            for item in menu_items:
                                item_normalized = _norm(item)
                                if (
                                    item_normalized in normalized
                                    or normalized in item_normalized
                                ):
                                    resolved = item
                                    break
                        if resolved is not None:
                            try:
                                shading.set(resolved)
                            except hou.OperationFailed:
                                resolved = None
                        if resolved is None:
                            debug.note("geometry thumbnail - no shading "
                                "menu token matches '" + wanted + "'; this "
                                "build offers: " + ", ".join(menu_items))
                    preview.safe_set(rop, "wireblend", 1.0)  # full strength: the flipbook default wireblend=0.5 half-fades wires toward the geo colour, which read fine against the bright grey-sky renders but disappears once the solid background removes the sky and its LIGHT
                    preview.safe_set(rop, "wirewidth", 1.0)
                    bg_mode = getattr(  # background from Preferences: the flipbook's own backdrop is its procedural sky (the washed grey = skyground 0.2 in the parm dump), and a solid bgimage replaces it deterministically for contrast
                        self._preferences, "geometry_bg", "black"
                    )
                    if bg_mode in ("black", "white"):
                        bg_file = amaze.package_file(
                            "res", "img", "geo_bg_%s.png" % bg_mode)
                        if os.path.exists(bg_file):
                            preview.safe_set(rop, "bgimage", bg_file)
                            preview.safe_set(rop, "skyusesky", 0)
                        else:
                            debug.note("geometry thumbnail - bg image "
                                "missing at " + bg_file)
                    look_key = (wanted, bg_mode)  # re-announces whenever the LOOK changes, a mid-session Preferences flip of mode/bg included, so the debug log always names what the newest renders used (debug.event only, so nothing is printed and nothing is recorded with Debug Mode off)
                    if look_key != getattr(
                        ThumbNailRenderer, "_geo_look_announced", None
                    ):
                        ThumbNailRenderer._geo_look_announced = look_key
                        try:
                            in_effect = shading.evalAsString() if shading else "?"
                        except hou.Error:
                            in_effect = "?"
                        debug.event(
                            "geo", "look in effect", shading=in_effect,
                            wireblend=rop.parm("wireblend").eval()
                            if rop.parm("wireblend") else "?",
                            bg=bg_mode,
                        )
                else:
                    with hou.undos.disabler():
                        candidate.destroy()
            except hou.OperationFailed:
                rop = None
            if rop is None:
                try:
                    with hou.undos.disabler():
                        rop = hou.node("/out").createNode("karma")
                    renderer_used = "karma ROP (CPU)"
                except hou.Error:
                    debug.note("geometry thumbnail - neither flipbook "
                        "nor karma ROP available, skipped")
                    return False
                preview.safe_set(rop, "engine", "cpu")
                preview.safe_set(rop, "samplesperpixel", 9)
            if renderer_used != getattr(
                ThumbNailRenderer, "_geo_rop_announced", None
            ):
                ThumbNailRenderer._geo_rop_announced = renderer_used
                parms = {}  # ground truth once per session: the renderer plus the COMPLETE parm list with current values, into the debug log rather than the console
                for p in rop.parms():
                    try:
                        parms[p.name()] = str(p.eval())
                    except hou.Error:
                        parms[p.name()] = "?"
                debug.event("geo", "rop in effect", rop=renderer_used,
                            rop_type=rop.type().name(), parms=parms)
            preview.safe_set(rop, "tres", 1)  # square resolution override tried across the common parm namings, whichever exists on this build wins; the dump above names the parms this ROP has, but it runs BEFORE these sets so its values are the pre-override ones
            preview.safe_set(rop, "res1", size)
            preview.safe_set(rop, "res2", size)
            preview.safe_set(rop, "res_overridex", size)
            preview.safe_set(rop, "res_overridey", size)
            preview.safe_set(rop, "aspect", 1.0)
            preview.safe_set(rop, "trange", 0)
            cam_parm = rop.parm("camera")
            if cam_parm is None:
                debug.note("geometry thumbnail - ROP has no camera "
                    "parm, skipped")
                return False
            cam_parm.set(cam.path())
            picture_parm = rop.parm("picture") or helpers.find_file_parm(rop)
            if picture_parm is None:
                debug.note("geometry thumbnail - no output picture parm "
                    "found on the " + rop.type().name() + " ROP, skipped")
                return False
            picture_parm.set(out_path)
            rop.render()
            if not os.path.exists(out_path):  # an ESC lands here too: the flipbook returns without raising when interrupted mid-render, so an escaped render is indistinguishable from a renderer that declined the file
                debug.note("geometry thumbnail - render ended without "
                    "an image for " + base + " (interrupted mid-"
                    "render, or the renderer declined the file)")
                return False
            return True
        finally:  # BOTH ends off the undo stack, like create_thumb_sop: a destroy left on the stack is itself undoable, which is how a thumbnail's scaffold comes back on Ctrl+Z
            with hou.undos.disabler():
                for node in (rop, light, cam, geo):
                    if node is not None:
                        try:
                            node.destroy()
                        except hou.ObjectWasDeleted:
                            pass

    def render_network_thumbnail(self, context, asset_id: str,
                                 thumb_node: str = "") -> bool | None:
        """The single Cop-or-Sop resolver for both doors - the save side (render/nodes.py) passes a child category name like Sop or Cop, Update Preview (core/cop_library.py) passes a renderer tag like SOP, COP or empty for assets saved before contexts were recorded - and the ESC interrupt shell lives here so both doors behave the same; returns None when the context has no picture to render (Lop, Dop... - the caller owns what that means at its door), else whether the render succeeded. A source scan in test_nodes_section keeps create_thumb_sop and create_thumb_cop callable only from here."""
        ctx = str(context or "").strip().lower()
        if ctx not in ("sop", "cop", ""):
            return None
        with hou.InterruptableOperation(
            "Rendering", "Performing Tasks", open_interrupt_dialog=True
        ):
            if ctx == "sop":  # an empty ctx falls through to the COP renderer below - assets saved before the section knew about contexts are all Copernicus
                return bool(self.create_thumb_sop(str(asset_id)))
            return bool(self.create_thumb_cop(str(asset_id),
                                              str(thumb_node)))

    def create_thumb_sop(self, asset_id: str) -> bool:
        """Thumbnail for a saved SOP-network asset (the Nodes section), rendered from the ARCHIVE and never the scene: the saved items load into a throwaway /obj container, its terminal SOP is written to a temporary scratch geometry file, and that file goes through create_thumb_geo_file - the same camera-fit-and-flipbook renderer the Geometry section uses - so a re-render still works long after the original nodes are gone. Every failure prints an Amaze-prefixed reason and returns False, which the caller must read as saved-without-a-thumbnail, never as a save failure."""
        out_path = tile_icons.thumbnail_path(self._preferences, asset_id)
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        if not os.path.exists(file_name):
            debug.note("SOP thumbnail - asset file missing")
            return False
        temp = None
        tmp_geo = ""
        try:
            with hou.undos.disabler():  # off the undo stack: this container is an implementation detail of taking a picture, and on the live stack the user's next Ctrl+Z resurrects a stray /obj/geo full of the asset's nodes instead of undoing what they actually did (research.md ▸ Undo)
                temp = hou.node("/obj").createNode("geo")
                for child in temp.children():
                    child.destroy()      # the default file SOP
            try:
                temp.loadItemsFromFile(file_name)
            except (OSError, hou.Error) as exc:
                debug.note("SOP thumbnail - could not load the asset "
                    "(%s)" % exc)
                return False
            children = [c for c in temp.children()
                        if isinstance(c, hou.SopNode)]
            if not children:
                debug.note("SOP thumbnail - no SOP nodes in the asset")
                return False
            target = next((c for c in children if c.isDisplayFlagSet()), None)  # the display node if the archive kept one
            if target is None:
                terminals = [c for c in children if not c.outputs()]  # else a terminal - nothing consumes its output
                target = terminals[-1] if terminals else children[-1]  # else simply the last
            tmp_geo = hostos.unique_scratch(  # UNIQUE, not a fixed name in a directory every Houdini process on this machine shares: two sessions pressing Update Preview on the same asset wrote one buffer, the second cooking a half-written file while the first deleted it from under it
                os.path.join(hostos.cache_root(),
                             "sop_thumb_%s.bgeo" % asset_id),
                suffix=".geo", create=False)
            try:
                target.geometry().saveToFile(tmp_geo)
            except (hou.Error, AttributeError) as exc:
                debug.note("SOP thumbnail - %s produced no geometry "
                    "(%s)" % (target.name(), exc))
                return False
            return self.create_thumb_geo_file(
                tmp_geo, out_path, int(self._preferences.rendersize)  # rendersize, NOT thumbsize: thumbsize is the grid's size SLIDER, so baking it into the file would freeze whatever the slider happened to read at save time
            )
        except Exception as exc:                        # noqa: BLE001
            debug.note("SOP thumbnail failed (%s)" % exc)
            return False
        finally:
            if temp is not None:
                try:
                    with hou.undos.disabler():
                        temp.destroy()
                except hou.Error:
                    pass
            if tmp_geo and os.path.exists(tmp_geo):
                try:
                    os.remove(tmp_geo)
                except OSError:
                    pass

    def create_thumb_cop(self, asset_id: str, source_name: str = "") -> bool:
        """Thumbnail for a standalone COP-network asset (the v2 Cop section): the network's own display/output image IS the thumbnail - no shaderball, lights or camera - rendered from a temporary copy loaded from the just-saved asset file (never the scene node) through a rop_image created inside that copy, which is always destroyed. Every failure path prints an Amaze-prefixed reason; callers treat False as registered-without-a-thumbnail, never as a save failure."""
        out_path = tile_icons.thumbnail_path(self._preferences, asset_id)
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        temp = None
        try:
            with hou.undos.disabler():  # off the undo stack, like create_thumb_sop's container and for the reason research.md ▸ Undo names thumbnails for explicitly: on the stack the user's next Ctrl+Z resurrects this copy instead of undoing what they actually did
                temp = hou.node("/obj").createNode("copnet")
            temp.loadItemsFromFile(file_name, ignore_load_warnings=True)

            out = None
            if source_name:  # the RECORDED name wins: save_node_cop picks the display node off the LIVE network at save time and persists its name, because flag state does not reliably survive the items-file round-trip
                out = temp.node(source_name)
                if out is None:
                    debug.note("COP thumbnail - recorded source node '"
                        + source_name
                        + "' not found in the loaded copy, falling back")
            if out is None:
                out = self._pick_cop_thumb_source(temp)  # the heuristic chain, fallback only, for assets saved before the source name was recorded
            if out is None:
                debug.note("COP thumbnail - network is empty, skipped")
                return False

            rop = temp.createNode("rop_image")
            out_index = 0  # multi-output nodes (sim blocks etc.): prefer the output actually named like a color image over a blind index 0
            out_name = ""
            try:
                names = list(out.outputNames())
                for i, name in enumerate(names):
                    lowered = name.lower()
                    if "color" in lowered or "rgb" in lowered or lowered == "c":
                        out_index = i
                        out_name = name
                        break
                if not out_name and names:
                    out_name = names[0]
            except AttributeError:
                pass
            debug.event("thumb", "cop render", source=out.name(),
                        output=out_name or "")
            try:
                rop.setInput(0, out, out_index)
            except hou.InvalidInput:
                debug.note("COP thumbnail - rop_image would not accept "
                    "the output node as input, skipped")
                return False
            picture_parm = helpers.find_file_parm(rop)  # found generically as the first FileReference string parm rather than by a hardcoded name - the same helper texture load-to-node uses
            if picture_parm is None:
                debug.note("COP thumbnail - no file parm found on "
                    "rop_image, skipped")
                return False
            picture_parm.set(out_path)

            if isinstance(rop, hou.RopNode):  # rop_image is ROP-like, so prefer the real render() call and fall back to pressing its execute button when it is not a hou.RopNode here
                rop.render()
            else:
                execute_parm = rop.parm("execute")
                if execute_parm is None:
                    debug.note("COP thumbnail - rop_image has no "
                        "execute parm to press, skipped")
                    return False
                execute_parm.pressButton()

            if not os.path.exists(out_path):
                debug.note("COP thumbnail - render finished but wrote "
                    "no image at " + out_path)
                return False
            return True
        finally:
            if temp is not None:
                with hou.undos.disabler():  # off the stack at BOTH ends, like create_thumb_sop
                    temp.destroy()

    def create_thumb_redshift(self, node: hou.Node, asset_id: str) -> bool:
        path = tile_icons.thumbnail_path(self._preferences, asset_id)
        with self._thumb_scene("Redshift") as (sc, thumb):
            self._setup_thumb_rop(thumb, node, path)
            preview.safe_set(  # rendersamples is the Redshift dial (Karma has its own karma_rendersamples); MAX only - the min stays at the ROP default so Redshift's adaptive sampling still decides how much of the budget each pixel needs
                sc.rop, "UnifiedMaxSamples", self._preferences.rendersamples
            )
            thumb.parm("render").pressButton()
            errors = helpers.node_errors(getattr(sc, "rop", None))
        return self._rendered(path, "Redshift", asset_id, errors)

    def create_thumb_octane(self, node: hou.Node, asset_id: str) -> bool:
        path = tile_icons.thumbnail_path(self._preferences, asset_id)
        with self._thumb_scene("Octane") as (sc, thumb):
            self._setup_thumb_rop(thumb, node, path)
            thumb.parm("render").pressButton()
            errors = helpers.node_errors(getattr(sc, "rop", None))
        return self._rendered(path, "Octane", asset_id, errors)
