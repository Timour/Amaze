"""Turn an online MaterialX record into a real library material. - Two paths, matching the two source KINDS: - * **package** - download the .mtlx + textures into <library>/matX/<name>/, then TRANSLATE the .mtlx into clean VOP nodes (core/matx_translate, built on Houdini's MaterialX Python API): fresh mtlximage / mtlxstandard_surface / ... nodes with real `file` inputs, flat in the builder, exactly like a hand-built material. (This replaced the old editmaterial LOP approach, which promoted every parameter and dropped the texture `file` inputs from the USD export - the black-material bug.) - * **values** - no download at all. Build an mtlxstandard_surface directly from the measured parameters (a tier-A preset material). - Everything temporary lives in /obj or /stage and is destroyed in a finally, so a failed import never leaves scene debris - the same discipline as the thumbnail and import paths."""

from __future__ import annotations

import os
import shutil

import hou

from amaze.core import debug, matx_sources, matx_translate
from amaze.helpers import helpers, hostos
from amaze.render import nodes as nodes_mod

MATX_DIRNAME = "matX"   # folder inside the library holding downloaded MaterialX sources - PERMANENT, not staging: the imported network's mtlximage nodes point at these texture files

CM_TO_SCENE_UNITS = 0.01   # PhysicallyBased subsurfaceRadius is a mean-free-path DISTANCE in CENTIMETRES (verified: their Milk [1.842,1.044,0.35] is the standard skimmed-milk value [18.42,10.44,3.50] mm / 10), and Houdini's mtlxstandard_surface subsurface_radius is likewise a distance rather than a 0-1 tint, multiplied by subsurface_scale - Houdini/USD scenes are METRES by default, so this converts the cm radius to metres, and feeding the raw cm value with scale 1 scattered ~100x too far and washed dark materials out to white/yellow (nudge only if a scene's unit scale differs, e.g. 1.0 for a centimetre scene)


def matx_dir(library_dir: str) -> str:
    return os.path.join(library_dir, MATX_DIRNAME)


def _credit_text(record, source) -> str:
    """The about/homage block for a downloaded material: source, author, and a link back to where it came from. Editable afterwards in the Material Info dialog."""
    lines = ['"%s" from the %s library.' % (record.title, record.source)]
    if record.author:
        lines.append("Created by %s." % record.author)
    url = ""
    try:
        url = source.page_url(record) or ""
    except Exception:
        url = ""
    if url:
        lines.append(url)
    lines.append("Please credit the creator as the license requires.")
    return "\n".join(lines)



def _values_to_standard_surface(values: dict, builder: hou.Node) -> hou.Node:
    """PhysicallyBased measured values -> mtlxstandard_surface constants. - Only maps what the source actually measures; anything absent is left at the shader default rather than invented. - Units, verified against the PhysicallyBased schema (github.com/AntonPalmqvist/physically-based-api) and the MtlX Standard Surface, so the physical values land at the right scale: - * color / specularColor linear rec709 RGB -> as-is * metalness / roughness 0..1 -> as-is * ior dielectric refractive index -> as-is * subsurfaceRadius mean free path, CENTIMETRES -> x CM_TO_SCENE_UNITS (via subsurface_scale; radius is a distance) * transmissionDepth Beer-Lambert depth, METRES -> as-is (OpenPBR convention; scene default is metres) * transmissionDispersion Abbe number (Diamond 55.3) -> as-is * thinFilmThickness NANOMETRES (Pearl 420) -> as-is * thinFilmIor refractive index -> as-is * complexIor handled elsewhere: a material carrying n,k is routed to _values_to_conductor_surface (a real conductor BSDF) instead of this function"""
    shader = builder.createNode("mtlxstandard_surface")

    def _set(parm_name, value):
        if value is None:
            return
        try:
            if isinstance(value, (list, tuple)):
                pt = shader.parmTuple(parm_name)
                if pt is not None:
                    pt.set(tuple(float(v) for v in value)[: len(pt)])
            else:
                p = shader.parm(parm_name)
                if p is not None:
                    p.set(float(value))
        except hou.Error as exc:
            debug.event("import", "shader parm not set",   # note vs event for this file: a per-parameter set failure is developer detail and fires inside a loop, so event - and the parm name is data rather than part of the sentence, because event()'s flood guard keys on the message, while the unresolved-texture line further down is what the user can actually see (inputs rendering black) and is a note
                        parm=parm_name, error=str(exc))

    _set("base_color", values.get("color"))
    _set("metalness", values.get("metalness"))
    _set("specular_roughness", values.get("roughness"))
    _set("specular_IOR", values.get("ior"))
    _set("specular_color", values.get("specularColor"))
    _set("transmission", values.get("transmission"))   # transmission (Glass, Water, liquid Honey...): a transmissive material tints the light passing THROUGH it by its own color, Standard Surface's transmission_color is that tint and defaults to white, so without this honey renders as clear as water - and in this dataset transmission is only ever 1, so any transmissive material also gets its base color as the transmission tint
    if values.get("transmission"):
        _set("transmission_color", values.get("color"))
    _set("transmission_depth", values.get("transmissionDepth"))
    _set("transmission_dispersion", values.get("transmissionDispersion"))
    radius = values.get("subsurfaceRadius")   # subsurface scattering (crystallized Honey, Petroleum, Milk, Marble, Skin...) is NOT transmissive - the source gives a per-channel subsurfaceRadius instead, and subsurface_radius alone does nothing until the subsurface WEIGHT is on and it has a color, so enable it fully and tint it with the material's own color
    if radius:
        _set("subsurface", 1)   # subsurface_radius is a DISTANCE (mean free path) in the same scene units as everything else rather than a 0-1 tint, PhysicallyBased gives it in centimetres and subsurface_scale converts to the scene's metres (see CM_TO_SCENE_UNITS): physically grounded, keeping each material's own scattering distance (petroleum scatters further than honey), though SSS is still scene-scale dependent so on an unusually large or small object the user can scale subsurface_scale on the shader
        _set("subsurface_color", values.get("color"))
        _set("subsurface_radius", radius)             # physical cm values
        _set("subsurface_scale", CM_TO_SCENE_UNITS)   # cm -> scene metres

    if debug.is_on():
        debug.event(
            "import", "preset values applied",
            base_color=values.get("color"),
            transmission=values.get("transmission"),
            subsurfaceRadius=values.get("subsurfaceRadius"),
            metalness=values.get("metalness"),
            roughness=values.get("roughness"),
        )
    _set("thin_film_thickness", values.get("thinFilmThickness"))   # thin film IS safe to copy here, unlike the Redshift converter where it was a non-zero DEFAULT sitting on every metal and painted them iridescent - here it is measured, and only on the two materials that genuinely are thin-film, Pearl (420nm) and Soap Bubble (500nm)
    _set("thin_film_IOR", values.get("thinFilmIor"))
    return shader   # complexIor is handled on a SEPARATE path (a conductor BSDF, see _values_to_conductor_surface): this function only builds the dielectric/artistic-metal standard_surface case


def _values_to_conductor_surface(values: dict, builder: hou.Node) -> hou.Node:
    """A measured metal (PhysicallyBased complexIor) as a PHYSICALLY correct conductor rather than an artistic standard_surface metal. - complexIor is [nR, kR, nG, kG, nB, kB] - the refractive index n and extinction k per channel. mtlxconductor_bsdf takes exactly those (`ior` = n, `extinction` = k) and computes the real complex-Fresnel reflectance, wired into an mtlxsurface terminal. This is the true metal response (e.g. gold's colour comes out of its n,k, not a painted swatch), which is why the 30 metals are routed here."""
    ci = values.get("complexIor") or []
    conductor = builder.createNode("mtlxconductor_bsdf")

    def _set_tuple(parm_name, value):
        try:
            pt = conductor.parmTuple(parm_name)
            if pt is not None:
                pt.set(tuple(float(v) for v in value)[: len(pt)])
        except hou.Error as exc:
            debug.event("import", "shader parm not set",
                        parm=parm_name, error=str(exc))

    if len(ci) >= 6:
        _set_tuple("ior", (ci[0], ci[2], ci[4]))          # n per channel
        _set_tuple("extinction", (ci[1], ci[3], ci[5]))   # k per channel
    roughness = values.get("roughness")
    if roughness is not None:
        _set_tuple("roughness", (roughness, roughness))   # conductor_bsdf roughness is a vector2 (anisotropic) and the source gives one scalar, so set both axes to it

    surface = builder.createNode("mtlxsurface")
    surface.setNamedInput("bsdf", conductor, 0)   # conductor.out (BSDF) -> surface.bsdf; the funnel wires this mtlxsurface into the builder's suboutput surface terminal

    if debug.is_on():
        debug.event(
            "import", "conductor metal applied",
            name=values.get("name"),
            ior=(ci[0], ci[2], ci[4]) if len(ci) >= 6 else None,
            extinction=(ci[1], ci[3], ci[5]) if len(ci) >= 6 else None,
            roughness=roughness,
        )
    return surface




def record_name(record) -> str:
    """The NODE/USD name one online record builds under. - The title after USD sanitization, sidestepping Windows reserved device names (CON, NUL, COM1...). Fine for a node - Houdini uniquifies node names itself. NOT sufficient for a directory: package_dirname() exists because two different records can share a title, and a directory name carries no uniquifier of its own."""
    return hostos.safe_filename(
        helpers.sanitize_usd_path(record.title) or "Material")


def package_dirname(record) -> str:
    """The matX/<name> directory one record's package extracts into. - IDENTITY, not just a title. Two sources both offer a "Red Brick"; extracting the second into the first's directory interleaves two packages' textures, and the .mtlx that survives references a mixture. The source and uid are what make a record itself, so they are in the name - readable title first, identity after."""
    tail = hostos.safe_filename(
        "%s-%s" % (record.source or "src", record.uid or "0"))
    return "%s__%s" % (record_name(record), tail)


def _producer_for(record, source, resolution, preferences, progress=None):
    """Resolve one record to a `produce` callback for the Karma material engine: returns (produce, note, error). - This is the half of an online import that reaches the NETWORK - the download, the .mtlx repair, the measured values. It is deliberately separate from what the caller then does with the material (save it to the library, or build it straight into the scene), so both destinations share exactly one download path and one shader translation."""
    name = record_name(record)
    if record.kind == "values":   # this branch downloads too, now that the live catalogue lists materials the shipped table has never seen: an RGL uid absent from the table fetches its measured BSDF here, and a 404, a timeout or a corrupt file used to raise straight through import_record and build_in_scene as a traceback instead of a download failure
        try:
            fetched_values = source.fetch(record, None, None, progress)   # PROGRESS REACHES HERE TOO: this branch downloads when the shipped table does not know the material, and it was the one fetch call passing no callback, so the bar was shown by the site that asked the source properly and then never moved
        except Exception as exc:                        # noqa: BLE001
            debug.exception("measurement download", exc, uid=record.uid)
            return (None, "", "Could not read the measurement for %s: %s"
                    % (record.title, exc))
        values = fetched_values.get("values", {})
        if not values.get("color"):
            return (None, "", "%s has no usable measurement" % record.title)
        note = fetched_values.get("note", "")   # some values sources derive their numbers rather than publishing them (RGL reads a measured BSDF) - the note explains how, and belongs on the material

        def produce(builder):
            if values.get("complexIor"):   # measured metals (complexIor n,k) go through a real conductor BSDF; everything else is a standard_surface
                return _values_to_conductor_surface(values, builder)
            return _values_to_standard_surface(values, builder)

        return (produce, note, "")

    dest = os.path.join(matx_dir(preferences.dir), package_dirname(record))
    if os.path.isdir(dest) and os.listdir(dest):   # REFUSE AN OCCUPIED DESTINATION: with identity in the name, an existing directory means THIS record was already downloaded, and extracting over it replaces texture files a saved material may be referencing at render time
        debug.event("import", "package already on disk - reusing",
                    dest=dest)
        found = matx_sources._find_mtlx(dest)    # the one home for "the first .mtlx under a directory", shared with the fresh-fetch path
        if found:
            fetched = {"mtlx": found}
        else:
            return (None, "", "%s is already on disk but holds no "
                              ".mtlx - remove %s and try again"
                    % (record.title, dest))
    else:
        scratch = dest + ".downloading"   # FETCH INTO A SCRATCH SIBLING, PROMOTE ON SUCCESS: fetch used to write straight into dest, so a download dying part-way left a non-empty directory that the reuse check above reads as already downloaded - torn textures reused on every later import, or a permanent refusal when the .mtlx never arrived; the rename is what makes an occupied destination MEAN a complete package, and a surviving scratch is ours by construction (library-audit reports it as leftover) and is swept on the next attempt
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            fetched = source.fetch(record, resolution, scratch,
                                   progress=progress)
        except Exception as exc:                        # noqa: BLE001
            debug.exception("download", exc, url=record.payload, dest=dest)
            shutil.rmtree(scratch, ignore_errors=True)
            return (None, "", "Download failed: %s" % exc)
        scratch_mtlx = (fetched or {}).get("mtlx")   # VERIFIED BEFORE IT IS PROMOTED: the rename is what makes an occupied destination MEAN a complete package, and it ran BEFORE the .mtlx check below, so an archive that extracted files without one still took the destination and the reuse check at the top of this function then refused that record permanently until the folder was deleted by hand - checked while the files are still in the scratch, so a failure leaves `dest` untouched and the next attempt is an ordinary download
        if not scratch_mtlx or not os.path.exists(scratch_mtlx):
            shutil.rmtree(scratch, ignore_errors=True)
            debug.event("import", "download held no .mtlx - scratch "
                                  "dropped, destination untouched",
                        dest=dest)
            return (None, "", "No .mtlx document in the downloaded package")
        if os.path.isdir(scratch):
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)   # this branch means dest was absent or EMPTY - an empty husk cannot be renamed onto, and holds nothing
            os.rename(scratch, dest)
        fetched = {   # the fetch answered scratch paths; the files live at dest now
            key: (dest + value[len(scratch):]
                  if isinstance(value, str) and value.startswith(scratch)
                  else value)
            for key, value in (fetched or {}).items()
        }
    mtlx_path = fetched.get("mtlx")
    if not mtlx_path or not os.path.exists(mtlx_path):
        return (None, "", "No .mtlx document in the downloaded package")
    repairs = matx_sources.repair_mtlx_references(mtlx_path, dest)
    if repairs:
        debug.event("import", "mtlx references repaired",
                    material=name, repairs=repairs)
        unresolved = [r for r in repairs if not r["fixed_to"]]
        if unresolved:
            debug.note(   # THE consequence sentence for a half-repaired material: repair_mtlx_references states only the cause, because this is the line with the count and the material's name and both are notes, so naming the black render in both printed the same bad news twice for one import
                "%d of the textures for %s were not downloaded and "
                "could not be matched, so those inputs render black. "
                "The rest of the material came through."
                % (len(unresolved), name))

    def produce(builder):
        return matx_translate.build_material(mtlx_path, builder, name)

    return (produce, "", "")


def to_renderer(builder, scratch, name: str, renderer: str):
    """The builder the caller asked for: the Karma one as built, or its Redshift twin converted beside it in `scratch` with the Karma one gone. Answers (builder, shader, wired, report-or-None)."""
    if renderer != "Redshift":
        return builder, None, None, None
    from amaze.render import redshift_converter    # late: render/ reaches back into core/
    rs_builder, shader, wired, report = redshift_converter.convert_karma_builder(
        builder, scratch, name)
    builder.destroy()
    if report.skipped or report.approximated:
        debug.note("\n".join(report.summary_lines()))
    return rs_builder, shader, wired, report


def build_in_scene(record, source, resolution, destination, preferences,
                   progress=None, renderer: str = "Karma"):
    """Build one online record straight into the SCENE, under `destination` (a materiallibrary LOP or /mat). Returns (builder, reason). - The library is never touched: this is the just-want-the-material-here path, so what lands is a scene node like any the user builds by hand - keeping it is a deliberate Save to Amaze afterwards. The caller owns the undo group (the destination may itself have just been created). - Textures still download to the library's matX folder, which is the app's permanent texture store - Clean Up Library only ever scans the .mat/.interface/thumbnail directories, so a scene-only import's textures are not collected behind its back."""
    if destination is None:
        return (None, "No destination network for the material.")
    name = record_name(record)
    debug.event("import", "start to scene", title=record.title, name=name,
                source=record.source, kind=record.kind,
                destination=destination.path(), resolution=resolution)
    produce, note, error = _producer_for(
        record, source, resolution, preferences, progress
    )
    if error:
        return (None, error)
    with hou.undos.disabler():   # OFF THE UNDO STACK, and built in /obj staging to be moved in ONE step: creating nodes INSIDE a live material library retranslates the whole library per node (wiki) and a failed build leaves no debris in the user's network, while this staging is invisible yet createNode and destroy BOTH land on the live stack and one performUndo resurrects the node WITH its children (research.md ▸ Undo #278) - a single Ctrl+Z after Add to Library used to bring back /obj/matnet1 holding a duplicate of the material just imported; same answer nodes.staged_asset and thumbs.create_thumb_sop give for their staging containers, while the adjacent Import to Scene GROUPS instead because that one is a scene edit the user should be able to undo
        scratch = hou.node("/obj").createNode("matnet")
    try:
        builder, shader, wired = nodes_mod.build_karma_material(
            scratch, name, produce)
        if shader is None:
            return (None, "Could not build a shading network for " + name)
        if renderer == "Redshift":
            builder, shader, wired, _report = to_renderer(builder, scratch, name, renderer)
            if shader is None:
                return (None, "Could not convert %s to Redshift" % name)
        if not wired:
            debug.note(   # the engine's own verdict, said to the user rather than only to the log: the material is real and importable, refusing it would throw away work over something the artist can wire by hand, so this is a warning attached to a success rather than a failure
                "\"%s\" imported, but its surface output is not wired, "
                "so it renders black until it is connected." % name)
        moved = hou.moveNodesTo((builder,), destination)
        if not moved:
            return (None, "Could not move %s into %s"
                    % (name, destination.path()))
        builder = moved[0]
        helpers.auto_place(builder)
        if destination.type().name() == "materiallibrary":   # registered exactly as an import is: a library whose wildcard was narrowed or disabled would otherwise take the material as a node that renders nowhere
            nodes_mod.register_in_materiallibrary(destination, builder)
        try:
            comment = _credit_text(record, source)   # credit travels WITH the material: a scene import has no library row to carry its licence, so the node comment does, and a later Save to Amaze has something to inherit
            if record.licence:
                comment += "\nLicence: %s" % record.licence
            if note:
                comment += "\n\n%s" % note
            builder.setComment(comment)
        except hou.Error as exc:
            debug.event("import", "comment not set", error=str(exc))
        debug.event("import", "built in scene", name=name,
                    path=builder.path())
        return (builder, "")
    finally:
        try:
            with hou.undos.disabler():
                scratch.destroy()
        except (hou.OperationFailed, hou.ObjectWasDeleted):
            pass


def import_record(record, source, resolution, library, preferences,
                  progress=None, renderer: str = "Karma"):
    """Import one online record into `library` (a MaterialLibrary). - Returns (ok, reason). Never leaves scene debris on failure. progress (frac) is called with a 0..1 fraction during the download (package sources only - value sources have nothing to download)."""
    name = record_name(record)
    debug.event("import", "start", title=record.title, name=name,
                source=record.source, kind=record.kind,
                category=record.category, resolution=resolution)
    with hou.undos.disabler():   # OFF THE UNDO STACK: this is pure staging and nothing user-visible survives it, but createNode and destroy BOTH land on the live stack and one performUndo resurrects the node WITH its children (research.md ▸ Undo #278) - a single Ctrl+Z after Add to Library used to bring back /obj/matnet1 holding a duplicate of the material just imported; same answer nodes.staged_asset and thumbs.create_thumb_sop give for their staging containers, while the adjacent Import to Scene GROUPS instead because that one is a scene edit the user should be able to undo
        scratch = hou.node("/obj").createNode("matnet")
    try:
        produce, measurement_note, error = _producer_for(   # resolve the input FIRST (the part that can fail with I/O), then let the shared Karma material engine own the container, wiring and verification - the online importer is one ADAPTER whose `produce` callback builds the shader network and nothing more
            record, source, resolution, preferences, progress
        )
        if error:
            return (False, error)

        builder, shader, wired = nodes_mod.build_karma_material(
            scratch, name, produce)

        if shader is None:
            return (False, "Could not build a shading network for " + name)
        if renderer == "Redshift":    # the Karma network is the way in for every online source; the Redshift twin is what lands
            builder, shader, wired, _report = to_renderer(builder, scratch, name, renderer)
            if shader is None:
                return (False, "Could not convert %s to Redshift" % name)
        if not wired:
            debug.note(
                "\"%s\" was imported, but its surface output is not "
                "wired, so it renders black until it is connected."
                % name)

        library.add_asset(   # BY ID, never by position: add_asset stamps the node with its library id and its save can ADOPT another session's row, appended after ours via the merge, so a grown row count can be true for the wrong reason and the LAST row can be somebody else's material - the id is the identity and the length was only ever a proxy for it
            builder,
            record.category,
            ",".join(record.tags or []),
            False,
        )
        stamped = builder.userData("assetlib_id") or ""
        row = library.find_asset_row_by_id(stamped) if stamped else -1
        if row == -1:
            return (False, "%s could not be saved to your library, so "   # add_asset only appends when the save chain succeeded, and crediting the last row regardless would rewrite the renderer, credits and license of whatever UNRELATED material happens to be last in the library - the sentence also stops sending the user to the console, since nothing on this branch ever wrote there (add_asset's save chain reports through the log) and with the prints gone that instruction opened an empty window
                           "it was not added. Your scene is unchanged."
                           % name)
        try:
            credited = library.assets[row]   # add_asset() derives the renderer from the NODE and a builder full of mtlx* nodes reads as Karma, which is exactly right since online imports ARE Karma materials rather than a renderer of their own - what is left is crediting the creators
            credited.about = _credit_text(record, source)    # written to the record and moved into the asset's COMMENT by the sweep below, which is where the credit lives now ▸p/d03-retired
            credited.license = record.licence or ""
            if measurement_note:
                credited.description = measurement_note
            library.save()
            library.adopt_retired_text_into_notes()    # the credit lands in the COMMENT through the one door that moves it, so an import and an old library reach the same place ▸p/d03-retired
        except Exception as exc:
            debug.exception("credit the import", exc)
            debug.event("import", "credit not written", error=str(exc))
        debug.event("import", "registered", name=name,
                    rows=library.rowCount())
        return (True, "")
    finally:
        try:
            with hou.undos.disabler():
                scratch.destroy()
        except (hou.OperationFailed, hou.ObjectWasDeleted):
            pass
