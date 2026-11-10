import functools
import os
import shutil
import tempfile
import hou

from amaze.core import debug
from amaze.core import material
from amaze.core import renderers
import amaze
from amaze.core import tile_icons
from amaze.render import husk_job
from amaze.render import nodes
from amaze.render.material_conversion import engine as conversion_engine
from amaze import messages
from amaze import preview
from amaze.prefs import prefs
from amaze.helpers import helpers, hostos

# (module reloads consolidated into panel.py's single chain)


def _undo_free(method):
    """`method` run whole inside one undo disabler: its staged work is nobody's Ctrl+Z."""
    @functools.wraps(method)
    def run(*args, **kwargs):
        with hou.undos.disabler():    # nests safely in a caller's ▸r/undo-groups
            return method(*args, **kwargs)
    return run


def usd_renderer(mat) -> str:
    """`Karma`, `Octane` or `Redshift`: the husk a material renders in; "" for a renderer with none."""
    if renderers.is_karma(mat.renderer):
        return "Karma"
    for name in ("Octane", "Redshift"):
        if name in str(mat.renderer):
            return name
    return ""


class ThumbNailRenderer:
    def __init__(
        self, preferences: prefs.Prefs, mat: material.Material | None = None
    ) -> None:
        self._mat = mat
        self._preferences = preferences  # the caller's own Prefs, not reloaded here
        self._builder = None

    @staticmethod
    def render_batch(preferences, renderer: str, items) -> bool:
        """Every (asset_id, node) in ONE background husk, a frame each; False if none can start."""
        items = [(str(asset_id), node) for asset_id, node in items if node is not None]
        if not items:
            return False
        try:
            scaffold = preview.build_usd_scaffold(preferences, renderer)    # one stage, the batch's
        except hou.Error as exc:    # a renderer this Houdini lacks refuses its settings node
            debug.exception("thumbnail stage", exc, renderer=renderer, materials=len(items))
            return False
        if scaffold is None:    # no Scene Viewer to read OCIO from
            return False
        job_dir = tempfile.mkdtemp(prefix="amaze_thumbs_",
                                   dir=hou.getenv("HOUDINI_TEMP_DIR") or None)
        try:
            batch = preview.write_batch(scaffold, items, job_dir)
        except hou.Error as exc:
            debug.exception("thumbnail batch", exc, renderer=renderer, materials=len(items))
            shutil.rmtree(job_dir, ignore_errors=True)
            return False
        except BaseException:
            shutil.rmtree(job_dir, ignore_errors=True)    # not ours to answer, but the folder is
            raise
        finally:
            with hou.undos.disabler():    # a bare destroy brings the scaffold back on Ctrl+Z
                scaffold["net"].destroy()
        frames = [(asset_id, tile_icons.thumbnail_path(preferences, asset_id))
                  for (asset_id, _node), prim in zip(items, batch["prims"]) if prim]
        batch["prims"] = [prim for prim in batch["prims"] if prim]
        if not frames:    # no material node in any of them
            shutil.rmtree(job_dir, ignore_errors=True)
            return False
        husk_job.jobs.submit(husk_job.HuskJob(batch, job_dir, frames),
                             blocking=not hou.isUIAvailable())
        return True

    @staticmethod
    def render_assets(preferences, mats) -> None:
        """Re-render library materials: each renderer's in ONE husk; one with no husk is named."""
        groups = {}
        refused = []
        for mat in mats:
            renderer = usd_renderer(mat)
            if renderer:
                groups.setdefault(renderer, []).append(mat)
            else:
                refused.append(messages.THUMBNAIL_RENDERER_NOT_LOADED
                               % (mat.name, renderers.label(mat.renderer)))
        if not preview.ocio_from_viewer():    # every renderer takes its OCIO from a Scene Viewer
            debug.event("thumb", "no scene viewer - the batch renders nothing")
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(messages.NO_SCENE_VIEWER_FOR_THUMBNAIL,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        for renderer, group in groups.items():
            ThumbNailRenderer._render_group(preferences, renderer, group)
        ui = getattr(hou, "ui", None)
        if refused and ui is not None:    # ONE message for the rows no husk renders
            ui.displayMessage("\n".join(refused),
                              title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)

    @staticmethod
    def _render_group(preferences, renderer: str, mats) -> None:
        """Import each into /mat, write the batch from them, and clear them away again."""
        handlers = []
        items = []
        refused = []
        api = conversion_engine.api(renderer)
        if api is not None and not api.available():    # its stage cannot be built here
            refused = [messages.THUMBNAIL_RENDERER_NOT_LOADED % (mat.name, renderers.label(renderer))
                       for mat in mats]
            mats = ()    # nothing imported, so render_batch has nothing to stage
        with hou.undos.disabler():    # the imports and their cleanup are a pair ▸r/undo-groups
            try:
                for mat in mats:
                    handler = nodes.NodeHandler(preferences)
                    ok, reason, _created = handler.import_asset_to_scene(mat, target="mat")
                    handlers.append(handler)
                    if ok:
                        items.append((mat.mat_id, handler.builder_node))
                    elif reason:
                        refused.append(reason)
                ThumbNailRenderer.render_batch(preferences, renderer, items)
            finally:
                for handler in handlers:
                    handler.cleanup()    # the stage is written: husk reads the file, not these
        ui = getattr(hou, "ui", None)
        if refused and ui is not None:    # ONE message for the batch
            ui.displayMessage("\n".join(refused),
                              title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)

    def create_thumbnail(self) -> None:
        """Render this material's thumbnail in the background: a batch of one."""
        ThumbNailRenderer.render_assets(self._preferences, [self._mat])

    def create_thumb(self, renderer: str, node, asset_id: str) -> bool:
        """One material's thumbnail in its `renderer`'s stage, in the background: a batch of one."""
        return self.render_batch(self._preferences, renderer, [(asset_id, node)])

    @staticmethod
    def _pick_cop_thumb_source(temp: hou.Node) -> hou.Node | None:
        """Fallback picker for assets saved without a recorded source-node name."""
        return helpers.pick_cop_display_child(temp)

    @_undo_free
    def create_thumb_geo_file(
        self, file_path: str, out_path: str, size: int
    ) -> bool:
        """Thumbnail for a geometry file via the flipbook ROP; False means no thumbnail, not an error."""
        from amaze.core import geo_library  # lazy: geo_library imports this module at top level
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
            preview.safe_set(geo, "rx", -20.0)  # the 3/4 view rotates the geo container; the camera is only translated
            preview.safe_set(geo, "ry", 35.0)
            rot = hou.hmath.buildRotate(hou.Vector3(-20.0, 35.0, 0.0))  # the same rotation as the container parms above

            with hou.undos.disabler():
                cam = hou.node("/obj").createNode("cam")
            preview.safe_set(cam, "resx", size)
            preview.safe_set(cam, "resy", size)
            min_vec = bbox.minvec()  # fit is axis-aligned in world space: world x/y are the image axes
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
            ortho_width = max(half_x, half_y, 0.0005) * 2.0 * 1.1  # the larger half-extent, floored, doubled, plus a 10% margin
            distance = half_z * 2.0 + ortho_width

            preview.safe_set(cam, "tx", world_center[0])
            preview.safe_set(cam, "ty", world_center[1])
            preview.safe_set(cam, "tz", world_center[2] + distance)  # straight in front of the geometry on +Z, translation only
            preview.safe_set(cam, "projection", "ortho")  # ortho, so framing is one number, orthowidth, under every renderer
            preview.safe_set(cam, "orthowidth", ortho_width)
            preview.safe_set(cam, "near", max(distance * 0.001, 0.00001))  # near/far scale off the fitted distance; Vulkan honours clip planes strictly
            preview.safe_set(cam, "far", distance + half_z * 4.0 + ortho_width)
            with hou.undos.disabler():
                light = hou.node("/obj").createNode("envlight")

            rop = None
            renderer_used = ""
            try:
                with hou.undos.disabler():
                    candidate = hou.node("/out").createNode("flipbook")  # renders with the viewport's configured renderer
                if candidate.parm("camera") is not None:  # no camera parm: destroyed below, and the Karma CPU fallback takes over
                    rop = candidate
                    renderer_used = "flipbook ROP (viewport renderer)"
                    preview.safe_set(cam, "orthowidth", ortho_width * 2.0)  # quadrant compensation, flipbook only; never gate on device scale ▸r/platform-files
                    preview.safe_set(cam, "tx", world_center[0] + ortho_width * 0.5)  # half the intended span, not the doubled one
                    preview.safe_set(cam, "ty", world_center[1] + ortho_width * 0.5)
                    preview.safe_set(rop, "vobjects", geo.path())  # scoped to our nodes, not the user's whole /obj scene and lights
                    preview.safe_set(rop, "alights", light.path())
                    shading = rop.parm("shadingmode")  # shading mode from Preferences, set by menu token, before the background block
                    wanted = getattr(
                        self._preferences,
                        "geometry_shading_mode",
                        "smoothwireshaded",
                    )
                    if shading is not None:
                        try:
                            menu_items = shading.parmTemplate().menuItems()  # maps the pref's long value onto this build's own menu tokens
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
                    preview.safe_set(rop, "wireblend", 1.0)  # full strength, so wires read against a solid background
                    preview.safe_set(rop, "wirewidth", 1.0)
                    bg_mode = getattr(  # background from Preferences: the flipbook's sky, or a solid bgimage
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
                    look_key = (wanted, bg_mode)  # logs the look whenever it changes; debug.event only
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
                parms = {}  # once per session: the renderer and every parm value, into the debug log
                for p in rop.parms():
                    try:
                        parms[p.name()] = str(p.eval())
                    except hou.Error:
                        parms[p.name()] = "?"
                debug.event("geo", "rop in effect", rop=renderer_used,
                            rop_type=rop.type().name(), parms=parms)
            preview.safe_set(rop, "tres", 1)  # square resolution override, across the parm namings this build may have
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
            if not os.path.exists(out_path):  # an ESC lands here too: an interrupted flipbook returns without raising
                debug.note("geometry thumbnail - render ended without "
                    "an image for " + base + " (interrupted mid-"
                    "render, or the renderer declined the file)")
                return False
            return True
        finally:  # both ends off the undo stack, like create_thumb_sop ▸r/undo-groups
            with hou.undos.disabler():
                for node in (rop, light, cam, geo):
                    if node is not None:
                        try:
                            node.destroy()
                        except hou.ObjectWasDeleted:
                            pass

    def render_network_thumbnail(self, context, asset_id: str,
                                 thumb_node: str = "") -> bool | None:
        """The one Cop-or-Sop thumbnail resolver: None when the context has no picture, else success."""
        ctx = str(context or "").strip().lower()
        if ctx not in ("sop", "cop", ""):
            return None
        with hou.InterruptableOperation(
            "Rendering", "Performing Tasks", open_interrupt_dialog=True
        ):
            if ctx == "sop":  # an empty ctx falls through to the COP renderer below
                return bool(self.create_thumb_sop(str(asset_id)))
            return bool(self.create_thumb_cop(str(asset_id),
                                              str(thumb_node)))

    @_undo_free
    def create_thumb_sop(self, asset_id: str) -> bool:
        """Thumbnail for a saved SOP asset, from the archive; False means no thumbnail, not a failure."""
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
            with hou.undos.disabler():  # off the undo stack ▸r/undo-groups
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
            tmp_geo = hostos.unique_scratch(  # a unique name: the scratch directory is shared by every Houdini process
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
                tmp_geo, out_path, int(self._preferences.rendersize)  # rendersize, not thumbsize, which is the grid's size slider
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

    @_undo_free
    def create_thumb_cop(self, asset_id: str, source_name: str = "") -> bool:
        """Thumbnail for a COP asset: its own output image; False means no thumbnail, not a failure."""
        out_path = tile_icons.thumbnail_path(self._preferences, asset_id)
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        temp = None
        try:
            with hou.undos.disabler():  # off the undo stack, like create_thumb_sop's container ▸r/undo-groups
                temp = hou.node("/obj").createNode("copnet")
            temp.loadItemsFromFile(file_name, ignore_load_warnings=True)

            out = None
            if source_name:  # the name recorded at save time wins over the fallback picker
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
            out_index = 0  # multi-output nodes: prefer an output named like a color image
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
            picture_parm = helpers.find_file_parm(rop)  # the first FileReference string parm
            if picture_parm is None:
                debug.note("COP thumbnail - no file parm found on "
                    "rop_image, skipped")
                return False
            picture_parm.set(out_path)

            if isinstance(rop, hou.RopNode):  # render(), else press its execute button
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
