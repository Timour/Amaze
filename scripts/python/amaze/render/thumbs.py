import contextlib
import os
import time
import hou

from amaze.core import debug
from amaze.core import material
from amaze.core import tile_icons
from amaze.render import nodes, thumbnail_scene
from amaze.prefs import prefs
from amaze.helpers import helpers, hostos, hostver

# (module reloads consolidated into panel.py's single chain)


def _node_errors(node):
    """Houdini's own cook errors/warnings for a node - the message that
    actually explains a failed render, which never reaches a print()."""
    if node is None:
        return {}
    out = {}
    for label, call in (("errors", "errors"), ("warnings", "warnings")):
        try:
            out[label] = list(getattr(node, call)())
        except Exception:
            pass
    return out


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

    def create_thumbnail(self) -> None:
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
                    self.create_thumb_mtlx(node_handler.builder_node, self._mat.mat_id)
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

    def build_karma_scaffold(self):
        """Build the reusable Karma thumbnail scaffold ONCE: the lopnet,
        the shaderball USD reference (the expensive part - a full stage
        composition), the floor material, the Karma render properties
        and the ROP. Everything here is identical for every material -
        only the material library and output paths change per render
        (see render_karma_into). Returns a scaffold dict, or None if no
        Scene Viewer is open (OCIO display/view come from it).

        Render All builds this once and reuses it across the whole
        batch instead of paying the USD stage load per material; a
        single render (create_thumb_mtlx) builds and destroys its own.
        """
        viewer = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
        if not viewer:
            return None

        display = viewer.getOCIODisplay()
        view = viewer.getOCIOView()

        space = "ACEScg"
        for s in hou.Color.ocio_spaces():
            if "acescg" in s.lower():
                space = s
                break

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
                hou.getenv("AMAZE")
                + "/scripts/python/amaze/res/usd/shaderBallScene2_Simple.usd"
            )

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

            preferences = net.createNode("karmarenderproperties")
            preferences.parm("camera").set("/shaderBallScene/cameras/RenderCam")
            preferences.parm("res_mode").set("manual")
            preferences.parm("res_mode").pressButton()
            preferences.parm("resolutionx").set(self._preferences.rendersize)
            preferences.parm("resolutiony").deleteAllKeyframes()
            preferences.parm("resolutiony").set(self._preferences.rendersize)
            # CPU engine, not XPU - much faster for small images like
            # these thumbnails (XPU's device startup overhead dominates
            # at this size). Samples from the Karma-specific pref
            # (default 9, Karma's own default) - deliberately NOT
            # prefs.rendersamples, which is the Redshift thumbnail dial
            # and lives at a very different scale (256).
            preferences.parm("engine").set("cpu")
            preferences.parm("engine").pressButton()
            preferences.parm("pathtracedsamples").set(
                self._preferences.karma_rendersamples
            )
            preferences.parm("enabledof").set(0)
            preferences.parm("enablemblur").set(0)

            rop = net.createNode("usdrender_rop")
            rop.parm("renderer").set("BRAY_HdKarma")  # Karma CPU
            rop.setFirstInput(preferences)
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
            "preferences": preferences,
            "rop": rop,
            "display": display,
            "view": view,
            "space": space,
        }

    def render_karma_into(self, scaffold, node, asset_id: str) -> bool:
        """Render one material into a pre-built scaffold. Creates and
        destroys ONLY the per-material nodes (the material library and
        the exr->png copnet); the scaffold's lopnet/reference/floor/
        render-properties/ROP persist for the next material. Identical
        pixels to the old single-shot create_thumb_mtlx - same wiring,
        same version branch, same cache-busting timestamped EXR."""
        net = scaffold["net"]
        lib1 = scaffold["lib1"]
        preferences = scaffold["preferences"]
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
            os.path.splitext(
                tile_icons.thumbnail_path(self._preferences, asset_id))[0],
            int(time.time() * 1000))

        lib = None
        copnet = None
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

            preferences.parm("picture").set(path)
            preferences.setFirstInput(lib)

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
                    rop_errors=_node_errors(rop),
                    lib_errors=_node_errors(lib),
                )
                debug.note("Karma thumbnail render produced no EXR "
                    "for " + str(asset_id) + " - keeping the old thumbnail")
                return False

            if hostver.has_new_cops():
                # Copnet Setup
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

                newpath = tile_icons.thumbnail_path(self._preferences, asset_id)

                cop_out.parm("copoutput").set(newpath)
                with debug.timed("batch", "exr->png conversion",
                                 asset_id=str(asset_id)):
                    cop_out.parm("execute").pressButton()

            else:  # Use Old COPs with restricted OCIO Capabilities
                # Copnet Setup
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

                newpath = tile_icons.thumbnail_path(self._preferences, asset_id)

                cop_out.parm("copoutput").set(newpath)
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

        # Measure the PNG that was actually written. "It looks black" is
        # ambiguous at tile size - an all-zero render, a transparent
        # image and a stale file are different bugs, and this tells them
        # apart without another round-trip.
        if debug.is_on():
            png = tile_icons.thumbnail_path(self._preferences, asset_id)
            debug.event("thumb", "karma thumbnail written",
                        asset_id=str(asset_id), **debug.image_stats(png))

        return True

    def create_thumb_mtlx(self, node: hou.Node, asset_id: str) -> bool:
        """Single Karma thumbnail: build a throwaway scaffold, render
        one material into it, destroy it. Render All uses the scaffold
        across the whole batch instead (build_karma_scaffold +
        render_karma_into)."""
        scaffold = self.build_karma_scaffold()
        if scaffold is None:
            return False
        try:
            return self.render_karma_into(scaffold, node, asset_id)
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
            sc = thumbnail_scene.ThumbNailScene(renderer)
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

        Through safe_set, like the ROP parms in thumbnail_scene.py: a
        renamed parm on a new renderer build is what safe_set exists to
        absorb, and setting these raw made it an AttributeError that
        aborts the render.
        """
        thumbnail_scene.safe_set(thumb, "mat", node.path())
        thumbnail_scene.safe_set(thumb, "path", out_path)
        thumbnail_scene.safe_set(thumb, "obj_exclude", "* ^" + thumb.name())
        thumbnail_scene.safe_set(thumb, "lights", thumb.name() + "/*")
        thumbnail_scene.safe_set(thumb, "resx", self._preferences.rendersize)
        thumbnail_scene.safe_set(thumb, "resy", self._preferences.rendersize)

    def _rendered(self, png_path: str, renderer: str, asset_id: str,
                  rop=None) -> bool:
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
        debug.event("thumb", "render produced no image",
                    renderer=renderer, asset_id=str(asset_id),
                    path=png_path,
                    errors=_node_errors(rop) if rop is not None else "")
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
                thumbnail_scene.safe_set(thumb, "cop_out_img", png_path)
                thumb.parm("render").pressButton()
            finally:
                # INSIDE the finally, same reason as render_karma_into.
                if os.path.exists(exr_path):
                    try:
                        os.remove(exr_path)
                    except OSError as exc:
                        debug.event("thumb", "intermediate not removed",
                                    path=exr_path, error=str(exc))
        return self._rendered(png_path, "Mantra", asset_id,
                              getattr(sc, "rop", None))

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
                        bg_file = (
                            hou.getenv("AMAZE")
                            + "/scripts/python/amaze/res/img/geo_bg_"
                            + bg_mode
                            + ".png"
                        )
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
                debug.note("geometry thumbnail - render finished but "
                    "wrote no image for " + base)
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
            tmp_geo = os.path.join(
                hostos.cache_root(), "sop_thumb_%s.bgeo" % asset_id
            )
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
            thumbnail_scene.safe_set(
                sc.rop, "UnifiedMaxSamples", self._preferences.rendersamples
            )
            thumb.parm("render").pressButton()
        return self._rendered(path, "Redshift", asset_id,
                              getattr(sc, "rop", None))

    def create_thumb_octane(self, node: hou.Node, asset_id: str) -> bool:
        path = tile_icons.thumbnail_path(self._preferences, asset_id)
        with self._thumb_scene("Octane") as (sc, thumb):
            self._setup_thumb_rop(thumb, node, path)
            thumb.parm("render").pressButton()
        return self._rendered(path, "Octane", asset_id,
                              getattr(sc, "rop", None))
