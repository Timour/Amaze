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
        self._preferences = preferences
        self._builder = None
        # Deliberately NO load() here. Every caller passes the panel's
        # own Prefs, which IS the authoritative in-memory copy; re-reading
        # settings.json on each thumbnail would discard unsaved edits,
        # re-run the install migration, and - as it did - silently
        # redirect a test fixture's library back at the real one.

    @staticmethod
    @contextlib.contextmanager
    def karma_batch(preferences):
        """One Karma scaffold for a whole batch, or None.

        The scaffold is a full USD stage composition - the expensive
        part of a Karma thumbnail, and identical for every material.
        `build_karma_scaffold` and `render_karma_into` were written to
        be reused across a batch and had no caller doing it: every
        render built its own and destroyed it, so re-rendering N
        materials paid the stage load N times.

        Yields the scaffold to pass into `create_thumbnail`, or None
        when there is no Scene Viewer to take OCIO display/view from -
        in which case every render falls back to building its own and
        the batch simply costs what it always did.

        Destroyed off the undo stack, both ends, for the reason
        `create_thumb_mtlx` gives: a bare destroy is the half that
        resurrects the whole scaffold on one Ctrl+Z.
        """
        scaffold = preview.build_karma_scaffold(preferences)
        try:
            yield scaffold
        finally:
            if scaffold is not None:
                with hou.undos.disabler():
                    scaffold["net"].destroy()

    def create_thumbnail(self, scaffold=None) -> None:
        """Render this material's thumbnail.

        `scaffold` is a Karma scaffold from `karma_batch` when this
        render is one of a batch; None builds and destroys its own,
        which is what a single render does.
        """
        node_handler = nodes.NodeHandler(self._preferences)
        if self._mat:
            # target="mat", NOT "auto". With "auto" the destination is
            # the user's ACTIVE editor, so rerendering a thumbnail while
            # a LOP network was in front imported into their
            # materiallibrary - and register_in_materiallibrary appends
            # an explicit entry when the builder is not already covered
            # by the wildcard. cleanup() destroys the node and nothing
            # removes the entry: reproduced, the entry survives and
            # names a node that no longer exists, which is the
            # "Ignoring missing explicit primitive" error this file
            # already names at line 249, on every cook from then on.
            #
            # A thumbnail has no business in the user's LOP context in
            # the first place - the Karma path builds its own lopnet
            # scaffold and the other three reference the material by
            # path - and forcing /mat also stops each rerender
            # retranslating their whole material library.
            ok, reason, _created = node_handler.import_asset_to_scene(
                self._mat, target="mat")
            if not ok:
                # No builder was created (e.g. a classic VOP material
                # while the active editor is a LOP context) - rendering
                # would proceed against a stale/absent node.
                if reason:
                    hou.ui.displayMessage(reason)  # type: ignore
                return

        try:
            with hou.InterruptableOperation(
                "Rendering", "Performing Tasks", open_interrupt_dialog=True
            ):
                if material.is_karma_renderer(self._mat.renderer):
                    if scaffold is not None:
                        # The batch's scaffold: rendered into, never
                        # destroyed here - karma_batch owns both ends.
                        preview.render_karma_into(
                            scaffold, node_handler.builder_node,
                            self._mat.mat_id,
                            tile_icons.thumbnail_path(
                                self._preferences, self._mat.mat_id))
                    else:
                        self.create_thumb_mtlx(
                            node_handler.builder_node, self._mat.mat_id)
                elif self._mat.renderer == "Mantra":
                    self.create_thumb_mantra(node_handler.builder_node, self._mat.mat_id)
                elif self._mat.renderer == "Redshift":
                    self.create_thumb_redshift(node_handler.builder_node, self._mat.mat_id)
                elif self._mat.renderer == "Octane":
                    self.create_thumb_octane(node_handler.builder_node, self._mat.mat_id)

                else:
                    pass
        finally:
            # Runs even if the user interrupts the render (ESC) so the
            # imported material copy never lingers in /mat.
            node_handler.cleanup()

    def create_thumb_mtlx(self, node: hou.Node, asset_id: str) -> bool:
        """Single Karma thumbnail: build a throwaway scaffold, render
        one material into it, destroy it. Render All uses the scaffold
        across the whole batch instead (build_karma_scaffold +
        render_karma_into)."""
        scaffold = preview.build_karma_scaffold(self._preferences)
        if scaffold is None:
            return False
        try:
            return preview.render_karma_into(
                scaffold, node, asset_id,
                tile_icons.thumbnail_path(self._preferences, asset_id))
        finally:
            # Runs even if the render is interrupted so no orphaned
            # lopnet (with live ROP) stays in /obj. Off the stack: the
            # create is disabled in build_karma_scaffold, and a bare
            # destroy is the half that resurrects the whole scaffold
            # on one Ctrl+Z (the BOTH-ends rule below).
            with hou.undos.disabler():
                scaffold["net"].destroy()

    @contextlib.contextmanager
    def _thumb_scene(self, renderer: str):
        """Yield (scene, thumb) and destroy the scene on every exit.

        The finally used to be written out three times with the same
        comment, and the boundary had already drifted: Mantra set its
        material parm BEFORE its try, so a missing `mat` parm or a
        deleted node raised where nothing cleaned up and left
        /obj/Thumbnail_Mantra in the user's scene - which is then saved
        into their hip file. Reproduced against a scene whose `mat`
        parm is absent: Mantra leaked, its two copies did not.

        Inside a `hou.undos.disabler()` for the reason create_thumb_sop
        already documents and research.md ▸ Undo names thumbnails for
        explicitly: without it the user's next Ctrl+Z resurrects the
        throwaway scene instead of undoing what they actually did.
        Measured: a createNode/destroy pair on the live stack comes
        back on one undo; the same pair inside a disabler does not.
        """
        with hou.undos.disabler():
            sc = preview.ThumbNailScene(renderer)
            thumb = sc.get_node()
            try:
                yield sc, thumb
            finally:
                # Runs even if the render is interrupted so no orphaned
                # thumbnail scene (with live ROP) stays in /obj.
                thumb.destroy()

    def _setup_thumb_rop(self, thumb, node: hou.Node, out_path: str) -> None:
        """The material/path/exclusion/light/resolution block the three
        renderer paths each carried their own copy of.

        Through safe_set, like the ROP parms in the preview engine: a
        renamed parm on a new renderer build is what safe_set exists to
        absorb, and setting these raw made it an AttributeError that
        aborts the render.
        """
        preview.safe_set(thumb, "mat", node.path())
        preview.safe_set(thumb, "path", out_path)
        preview.safe_set(thumb, "obj_exclude", "* ^" + thumb.name())
        preview.safe_set(thumb, "lights", thumb.name() + "/*")
        preview.safe_set(thumb, "resx", self._preferences.rendersize)
        preview.safe_set(thumb, "resy", self._preferences.rendersize)

    def _rendered(self, png_path: str, renderer: str, asset_id: str,
                  errors=None) -> bool:
        """Did the render actually write the image?

        The Karma path has always checked; Mantra, Redshift and Octane
        ended with a bare `return True` after pressing the button, so
        every caller's failure branch in nodes.py was unreachable and a
        render that produced nothing reported success. Per practice.md
        #364 a failed render keeps the OLD thumbnail, so the tile shows
        the previous image and nothing anywhere says the new one never
        happened.
        """
        if os.path.exists(png_path):
            return True
        # ALREADY GATHERED, by the caller, while the scene was still
        # alive. This used to take the ROP and read its errors HERE -
        # and every caller invokes this AFTER its `with self._thumb_scene`
        # block, which destroys the scene the ROP is a grandchild of. So
        # `node_errors` swallowed hou.ObjectWasDeleted into {} and the
        # one field that explains a failed render was empty by
        # construction, in the function whose docstring says capturing
        # it is the point.
        debug.event("thumb", "render produced no image",
                    renderer=renderer, asset_id=str(asset_id),
                    path=png_path, errors=errors or "")
        return False

    def create_thumb_mantra(self, node: hou.Node, asset_id: str) -> bool:
        # Build path. Intermediate EXR name is UNIQUE per render - same
        # image-cache staleness hazard as create_thumb_mtlx above.
        png_path = tile_icons.thumbnail_path(self._preferences, asset_id)
        exr_path = "%s.%d.exr" % (os.path.splitext(png_path)[0],
                                  int(time.time() * 1000))
        with self._thumb_scene("Mantra") as (sc, thumb):
            try:
                self._setup_thumb_rop(thumb, node, exr_path)
                preview.safe_set(thumb, "cop_out_img", png_path)
                thumb.parm("render").pressButton()
            finally:
                # INSIDE the finally, same reason as render_karma_into.
                if os.path.exists(exr_path):
                    try:
                        os.remove(exr_path)
                    except OSError as exc:
                        debug.event("thumb", "intermediate not removed",
                                    path=exr_path, error=str(exc))
            # INSIDE the block: the scene is destroyed on its way out
            # and the ROP goes with it.
            errors = helpers.node_errors(getattr(sc, "rop", None))
        return self._rendered(png_path, "Mantra", asset_id, errors)

    @staticmethod
    def _pick_cop_thumb_source(temp: hou.Node) -> hou.Node | None:
        """FALLBACK-ONLY picker for assets saved before the source-node
        name was recorded at save time (which is the reliable path -
        see create_thumb_cop). Shares the exact logic of the live pick
        via helpers.pick_cop_display_child so the two can't drift."""
        return helpers.pick_cop_display_child(temp)

    def create_thumb_geo_file(
        self, file_path: str, out_path: str, size: int
    ) -> bool:
        """Thumbnail for a geometry FILE (the v2 Geometry section):
        temp geo + the right loader SOP for the extension, orthographic
        camera fitted on the (container-rotated) bounding box, env
        light, rendered through the FLIPBOOK ROP (Vulkan viewport
        renderer; Karma CPU fallback) with the retina-quadrant
        compensation - the verified end state of an eleven-round
        debugging saga. Everything is destroyed in finally. Returns
        False (with an Amaze-prefixed console reason) on any failure
        - callers treat that as "no thumbnail", never an error."""
        # The ONE extension->loader mapping lives in geo_library
        # (imported lazily: geo_library imports this module at top
        # level, so the import direction only works this way around).
        from amaze.core import geo_library
        loader_type = geo_library.loader_sop_for(file_path)

        def _set(node, name, value):
            parm = node.parm(name)
            if parm is not None:
                try:
                    parm.set(value)
                except hou.OperationFailed:
                    pass

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
            except hou.OperationFailed:
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
            # THE step-back fix after the "still not centered" round:
            # the fit numbers and resolution were verified correct in
            # a live console capture, leaving exactly one suspect -
            # the hand-built lookat rotation matrix, the only hand math
            # left in the chain. It is now GONE ENTIRELY: the camera
            # keeps its DEFAULT orientation (identity looks down -Z, by
            # Houdini's own definition) and just gets translated to
            # straight in front of the geometry. The 3/4 view comes
            # from rotating the GEO CONTAINER instead, via plain rotate
            # parms, and the bbox corners are transformed by
            # hou.hmath.buildRotate - Houdini's own matrix builder,
            # Houdini's own conventions, nothing hand-rolled anywhere.
            _set(geo, "rx", -20.0)
            _set(geo, "ry", 35.0)
            rot = hou.hmath.buildRotate(hou.Vector3(-20.0, 35.0, 0.0))

            with hou.undos.disabler():
                cam = hou.node("/obj").createNode("cam")
            _set(cam, "resx", size)
            _set(cam, "resy", size)
            # ORTHOGRAPHIC framing (the "zoom out and find it" round):
            # perspective framing under the Vulkan rasterizer was too
            # tight by a large factor even though the IDENTICAL fit
            # math framed perfectly under Karma - meaning the two
            # renderers interpret the camera's perspective attributes
            # (aperture/focal/aspect/res-override crop semantics)
            # differently, and that interpretation isn't pinned down
            # anywhere scriptable. Ortho removes the entire question:
            # the visible width IS one number (orthowidth), no focal,
            # no aperture, no fov derivation - and it's the classic
            # product-shot look for asset thumbnails anyway. Fit: the
            # largest per-axis extent of any bbox corner projected onto
            # the camera's own x/y axes, plus margin.
            # Transform the LOCAL bbox corners into world space with
            # Houdini's own rotation matrix, then fit axis-aligned - the
            # camera has no rotation, so world x/y ARE the image axes.
            min_vec = bbox.minvec()
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
            ortho_width = max(half_x, half_y, 0.0005) * 2.0 * 1.1
            distance = half_z * 2.0 + ortho_width

            # Straight down +Z in front of the rotated geometry -
            # translation only, orientation stays identity.
            _set(cam, "tx", world_center[0])
            _set(cam, "ty", world_center[1])
            _set(cam, "tz", world_center[2] + distance)
            _set(cam, "projection", "ortho")
            _set(cam, "orthowidth", ortho_width)
            # The Vulkan rasterizer honors near/far clip planes strictly
            # (raytracers effectively don't) - scale them to the fitted
            # distance so no model scale can clip.
            _set(cam, "near", max(distance * 0.001, 0.00001))
            _set(cam, "far", distance + half_z * 4.0 + ortho_width)
            with hou.undos.disabler():
                light = hou.node("/obj").createNode("envlight")

            # Renderer: the FLIPBOOK ROP, per the H22 manual (standing
            # project rule) - opengl is "scheduled to be deleted",
            # flipbook is its designated replacement and has been
            # accepted by the strict camera check in an earlier round.
            # Its documented pages don't enumerate parms, so the node
            # ANNOUNCES its own relevant parm names once per session
            # (the "flipbook ROP parms" console line) - future
            # adjustments get made from that ground truth, not doc
            # archaeology. Karma CPU (a previously proven material
            # combination) is the fallback if flipbook is missing or
            # camera-less. NOTE: flipbook renders with the VIEWPORT's
            # configured renderer - with the viewport on the plain
            # Vulkan rasterizer it's fast; a viewport parked on a Karma
            # delegate makes every thumbnail a viewport-quality Karma
            # render (the earlier ~5min/file round).
            rop = None
            renderer_used = ""
            try:
                with hou.undos.disabler():
                    candidate = hou.node("/out").createNode("flipbook")
                if candidate.parm("camera") is not None:
                    rop = candidate
                    renderer_used = "flipbook ROP (viewport renderer)"
                    # EMPIRICAL RETINA-QUADRANT COMPENSATION. A full
                    # parm dump + screenshots decoded to: the
                    # flipbook's output is the LOWER-LEFT QUADRANT of a
                    # double-size framebuffer (visible span = exactly
                    # half the set orthowidth, subject displaced up-
                    # right by a quarter frame). This was originally
                    # attributed to the 2x Retina backing store; that
                    # was WRONG, and the correction matters because it
                    # inverts what the code should do. MEASURED
                    # 2026-07-28: 255 thumbnails through this same ROP
                    # on Windows at device_pixel_ratio 1.0 come out
                    # correct WITH the compensation applied. The
                    # doubling belongs to the flipbook capture, not to
                    # the display, so this must stay UNCONDITIONAL - a
                    # review proposed gating it on device scale, which
                    # would have halved and displaced every Windows
                    # thumbnail. Compensate:
                    # double the orthowidth and shift the camera center
                    # up-right by half the INTENDED span, so the
                    # captured quadrant IS the intended frame. Flipbook
                    # branch only - the Karma fallback renders the
                    # camera faithfully and must stay uncompensated. If
                    # SideFX fixes the capture this overcorrects in the
                    # exact opposite signature - subject at half size,
                    # displaced down-left - which is instantly
                    # recognizable and worth a bug report either way.
                    _set(cam, "orthowidth", ortho_width * 2.0)
                    _set(cam, "tx", world_center[0] + ortho_width * 0.5)
                    _set(cam, "ty", world_center[1] + ortho_width * 0.5)
                    # Scope the render to OUR nodes - the dump showed
                    # vobjects=* / alights=*, which pulls the user's
                    # whole /obj scene (and its lights) into every
                    # thumbnail.
                    _set(rop, "vobjects", geo.path())
                    _set(rop, "alights", light.path())
                    # Shading mode from Preferences (default: wire over
                    # shaded; plain shaded reads too flat).
                    # Set by menu token, verified by reading it back.
                    # Runs BEFORE the background block deliberately.
                    shading = rop.parm("shadingmode")
                    wanted = getattr(
                        self._preferences,
                        "geometry_shading_mode",
                        "smoothwireshaded",
                    )
                    if shading is not None:
                        # Resolve against the parm's OWN menu instead of
                        # guessing token spellings: live testing showed
                        # 'smoothwireshaded' rejected with the default
                        # landing on 'smooth' - the real tokens are the
                        # short forms ('smooth'/'smoothwire'/...). The
                        # pref keeps its long descriptive value; this
                        # maps it onto whatever this build actually
                        # offers. (Historical note: the round where
                        # wires WORKED did so via a set(9) index
                        # fallback that a later edit replaced with the
                        # same broken string token - that, not
                        # lighting, is when wires died.)
                        try:
                            menu_items = shading.parmTemplate().menuItems()
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
                    # Full-strength wires: the flipbook default is
                    # wireblend=0.5 (wires half-faded toward the geo
                    # color). That read fine against the bright grey-sky
                    # renders, but killing the sky for the solid
                    # background also removed its LIGHT - the mesh
                    # renders darker/flatter and half-blended wires
                    # disappear into it ("wireframe not respected").
                    _set(rop, "wireblend", 1.0)
                    _set(rop, "wirewidth", 1.0)
                    # Background from Preferences: the flipbook's own
                    # backdrop is its procedural sky (the washed grey =
                    # skyground 0.2 in the parm dump); a solid bgimage
                    # replaces it deterministically for contrast.
                    bg_mode = getattr(
                        self._preferences, "geometry_bg", "black"
                    )
                    if bg_mode in ("black", "white"):
                        bg_file = amaze.package_file(
                            "res", "img", "geo_bg_%s.png" % bg_mode)
                        if os.path.exists(bg_file):
                            _set(rop, "bgimage", bg_file)
                            _set(rop, "skyusesky", 0)
                        else:
                            debug.note("geometry thumbnail - bg image "
                                "missing at " + bg_file)
                    # Positive in-effect report - re-announces whenever
                    # the LOOK changes (a mid-session Preferences flip
                    # of mode/bg included), so the console always names
                    # what the newest renders used.
                    look_key = (wanted, bg_mode)
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
                except hou.OperationFailed:
                    debug.note("geometry thumbnail - neither flipbook "
                        "nor karma ROP available, skipped")
                    return False
                _set(rop, "engine", "cpu")
                _set(rop, "samplesperpixel", 9)
            if renderer_used != getattr(
                ThumbNailRenderer, "_geo_rop_announced", None
            ):
                ThumbNailRenderer._geo_rop_announced = renderer_used
                # Ground truth: renderer + the COMPLETE parm list with
                # current values, once per session, in the debug log -
                # closes every which-parm question without touching the
                # console.
                parms = {}
                for p in rop.parms():
                    try:
                        parms[p.name()] = str(p.eval())
                    except hou.Error:
                        parms[p.name()] = "?"
                debug.event("geo", "rop in effect", rop=renderer_used,
                            rop_type=rop.type().name(), parms=parms)
            # Square resolution override, tried across the common parm
            # namings - whichever exists on this build wins; the parm
            # list printed above shows which landed.
            _set(rop, "tres", 1)
            _set(rop, "res1", size)
            _set(rop, "res2", size)
            _set(rop, "res_overridex", size)
            _set(rop, "res_overridey", size)
            _set(rop, "aspect", 1.0)
            _set(rop, "trange", 0)
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
            if not os.path.exists(out_path):
                # NOT "finished": an ESC lands here too. The flipbook
                # returns without raising when interrupted mid-render,
                # so a big file whose render was escaped is
                # indistinguishable from a renderer that declined -
                # and the old sentence claimed the first was the
                # second, which cost a chase (2026-08-08, a 233MB STL
                # escaped 7s in, logged as wrote-no-image while the
                # very next line said the pass was interrupted).
                debug.note("geometry thumbnail - render ended without "
                    "an image for " + base + " (interrupted mid-"
                    "render, or the renderer declined the file)")
                return False
            return True
        finally:
            # BOTH ends off the undo stack, like create_thumb_sop: a
            # destroy left on the stack is itself undoable, which is
            # how a thumbnail's scaffold comes back on Ctrl+Z.
            with hou.undos.disabler():
                for node in (rop, light, cam, geo):
                    if node is not None:
                        try:
                            node.destroy()
                        except hou.ObjectWasDeleted:
                            pass

    def render_network_thumbnail(self, context, asset_id: str,
                                 thumb_node: str = "") -> bool | None:
        """THE Cop-or-Sop decision, made once for both of its doors -
        the save side (render/nodes.py, which reads a child category
        name like Sop or Cop) and Update Preview (core/cop_library.py,
        which reads a renderer tag like SOP, COP or empty for assets
        saved before contexts were recorded). It was typed at both
        doors and they could drift apart - the two-resolvers shape; a
        source scan in test_nodes_section keeps the verbs below
        callable only from here.

        Returns None when this context has no picture to render (Lop,
        Dop... - the caller owns what that means at its door), else
        whether the render succeeded. The interrupt shell lives here
        too, so ESC behaves the same at both doors.
        """
        ctx = str(context or "").strip().lower()
        if ctx not in ("sop", "cop", ""):
            return None
        with hou.InterruptableOperation(
            "Rendering", "Performing Tasks", open_interrupt_dialog=True
        ):
            if ctx == "sop":
                return bool(self.create_thumb_sop(str(asset_id)))
            # Empty covers assets saved before the section knew about
            # contexts - they are all Copernicus.
            return bool(self.create_thumb_cop(str(asset_id),
                                              str(thumb_node)))

    def create_thumb_sop(self, asset_id: str) -> bool:
        """Thumbnail for a saved SOP-network asset (the Nodes section).

        Rendered from the ARCHIVE, never the scene: the saved items are
        loaded into a throwaway /obj container, its terminal node is
        cooked to a temporary .bgeo, and that file goes through the
        SAME geometry renderer the Geometry section uses - the camera
        fit and flipbook path whose behaviour is already settled. Going
        via a file rather than refactoring that renderer keeps this
        change away from code that took a long time to get right.

        Rendering from the archive also means a re-render works long
        after the original nodes are gone.

        Every failure prints an Amaze-prefixed reason and returns
        False; the caller treats that as "saved without a thumbnail",
        never as a save failure.
        """
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
            # OFF the undo stack. This container is an implementation
            # detail of taking a picture; on the stack, the user's next
            # Ctrl+Z resurrects a stray /obj/geo full of the asset's
            # nodes instead of undoing what they actually did.
            with hou.undos.disabler():
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
            # The display node if the archive kept one, else a terminal
            # (nothing consumes its output), else simply the last.
            target = next((c for c in children if c.isDisplayFlagSet()), None)
            if target is None:
                terminals = [c for c in children if not c.outputs()]
                target = terminals[-1] if terminals else children[-1]
            # UNIQUE, not a fixed name in a directory every Houdini
            # process on this machine shares. Two sessions pressing
            # Update Preview on the same asset wrote one buffer: the
            # second cooked a half-written .bgeo and reported no
            # cookable geometry, and the first deleted the file from
            # under it. The `.mat`/`.interface` pair beside this
            # already goes through unique_scratch.
            tmp_geo = hostos.unique_scratch(
                os.path.join(hostos.cache_root(),
                             "sop_thumb_%s.bgeo" % asset_id),
                suffix=".geo", create=False)
            try:
                target.geometry().saveToFile(tmp_geo)
            except (hou.Error, AttributeError) as exc:
                debug.note("SOP thumbnail - %s produced no geometry "
                    "(%s)" % (target.name(), exc))
                return False
            # rendersize, NOT thumbsize: thumbsize is the grid's size
            # SLIDER, so baking it into the file would freeze whatever
            # the slider happened to read at save time. Every other
            # renderer here, Geometry included, uses rendersize.
            return self.create_thumb_geo_file(
                tmp_geo, out_path, int(self._preferences.rendersize)
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
        """Thumbnail for a standalone COP-network asset (the v2 Cop
        section): the network's own display/output image IS the
        thumbnail - no shaderball/lights/camera. Works on a temporary
        copy loaded from the just-saved asset file (never the scene
        node), writes the image via a rop_image COP created inside it,
        and always destroys the copy. Every failure path prints an
        Amaze-prefixed reason - callers treat False as
        "registered without a thumbnail", never as a save failure."""
        out_path = tile_icons.thumbnail_path(self._preferences, asset_id)
        file_name = material.payload_path(
            self._preferences, str(asset_id), self._preferences.ext
        )
        temp = None
        try:
            # OFF the undo stack, like create_thumb_sop's container
            # and for the reason research.md ▸ Undo names
            # thumbnails for explicitly: this is an implementation
            # detail of taking a picture, and on the stack the
            # user's next Ctrl+Z resurrects it instead of undoing
            # what they actually did.
            with hou.undos.disabler():
                temp = hou.node("/obj").createNode("copnet")
            temp.loadItemsFromFile(file_name, ignore_load_warnings=True)

            # The node whose image gets written. The RECORDED name wins:
            # save_node_cop reads the display flag off the LIVE network
            # at save time and persists the chosen node's name, because
            # flag state doesn't reliably survive the items-file
            # round-trip - two live tests picked wrong nodes in opposite
            # directions when heuristics ran on the loaded copy. The
            # heuristic chain below is only the fallback for assets
            # saved before the name was recorded.
            out = None
            if source_name:
                out = temp.node(source_name)
                if out is None:
                    debug.note("COP thumbnail - recorded source node '"
                        + source_name
                        + "' not found in the loaded copy, falling back")
            if out is None:
                out = self._pick_cop_thumb_source(temp)
            if out is None:
                debug.note("COP thumbnail - network is empty, skipped")
                return False

            rop = temp.createNode("rop_image")
            # Multi-output nodes (sim blocks etc.): prefer the output
            # actually named like a color image over a blind index 0.
            out_index = 0
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
            # The output-picture parm found generically (FileReference
            # string parm) rather than by a hardcoded name - same
            # mechanism as texture load-to-node (helpers.find_file_parm).
            picture_parm = helpers.find_file_parm(rop)
            if picture_parm is None:
                debug.note("COP thumbnail - no file parm found on "
                    "rop_image, skipped")
                return False
            picture_parm.set(out_path)

            # Render the single current frame: rop_image is ROP-like, so
            # prefer the real render() call, falling back to pressing
            # its execute button if it isn't a hou.RopNode here.
            if isinstance(rop, hou.RopNode):
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
                # Off the stack at BOTH ends, like create_thumb_sop.
                with hou.undos.disabler():
                    temp.destroy()

    def create_thumb_redshift(self, node: hou.Node, asset_id: str) -> bool:
        path = tile_icons.thumbnail_path(self._preferences, asset_id)
        with self._thumb_scene("Redshift") as (sc, thumb):
            self._setup_thumb_rop(thumb, node, path)
            # Sampling quality from the Redshift-specific pref. This ROP
            # previously set no sampling parms at all (rendered on ROP
            # defaults) - prefs.rendersamples' only consumer used to be
            # the Karma path, which now has its own karma_rendersamples,
            # so this pref is the Redshift dial now. Max only: the min
            # stays at the ROP default so Redshift's adaptive sampling
            # still decides how much of the budget each pixel needs.
            # AFTER the shared call, because it is a real difference
            # between the three and not a copy.
            preview.safe_set(
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
