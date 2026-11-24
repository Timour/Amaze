"""Turn an online MaterialX record, a package or measured values, into a library material."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile

import hou

from amaze.core import debug, library_files, material, matx_sources, matx_translate, renderers
from amaze.core import texstore
from amaze.helpers import helpers, hostos, wording
from amaze.render import nodes as nodes_mod
from amaze.render.material_conversion import engine as conversion_engine

SCENE_DOWNLOADS = "tex"    # in `$HIP`: the packages built in the scene, which reads them there


def _credit_text(record, source) -> str:
    """Source, author and a link back; it asserts no licence requirement ▸r/online-source-licences"""
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
    return "\n".join(lines)



def _values_to_standard_surface(values: dict, builder: hou.Node) -> hou.Node:
    """Measured values as an mtlxstandard_surface; absent values keep the default ▸r/rgl-values."""
    shader = builder.createNode("mtlxstandard_surface")

    def _set(parm_name, value):
        nodes_mod.set_shader_value(shader, parm_name, value, "import")

    _set("base_color", values.get("color"))
    _set("metalness", values.get("metalness"))
    _set("specular_roughness", values.get("roughness"))
    _set("specular_IOR", values.get("ior"))
    _set("specular_color", values.get("specularColor"))
    _set("transmission", values.get("transmission"))   # a transmissive material is tinted by its base color
    if values.get("transmission"):
        _set("transmission_color", values.get("color"))
    _set("transmission_depth", values.get("transmissionDepth"))
    _set("transmission_dispersion", values.get("transmissionDispersion"))
    radius = values.get("subsurfaceRadius")   # a radius turns subsurface fully on, tinted by base color
    if radius:
        _set("subsurface", 1)
        _set("subsurface_color", values.get("color"))
        _set("subsurface_radius", radius)             # physical cm values
        _set("subsurface_scale", material.CM_TO_SCENE_UNITS)   # cm -> scene metres

    if debug.is_on():
        debug.event(
            "import", "preset values applied",
            base_color=values.get("color"),
            transmission=values.get("transmission"),
            subsurfaceRadius=values.get("subsurfaceRadius"),
            metalness=values.get("metalness"),
            roughness=values.get("roughness"),
        )
    _set("thin_film_thickness", values.get("thinFilmThickness"))
    _set("thin_film_IOR", values.get("thinFilmIor"))
    return shader


def _values_to_conductor_surface(values: dict, builder: hou.Node) -> hou.Node:
    """A measured metal, complexIor [nR, kR, nG, kG, nB, kB], as a conductor BSDF in an mtlxsurface."""
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
        _set_tuple("roughness", (roughness, roughness))   # a vector2: the same value on both axes

    surface = builder.createNode("mtlxsurface")
    surface.setNamedInput("bsdf", conductor, 0)   # the caller wires this mtlxsurface to the terminal

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
    """The node and USD name a record is built with; not unique, so never a directory name."""
    return hostos.safe_filename(
        wording.sanitize_usd_path(record.title) or "Material")


def package_dirname(record) -> str:
    """The folder a record's package is downloaded into: title, then source and uid."""
    tail = hostos.safe_filename(
        "%s-%s" % (record.source or "src", record.uid or "0"))
    return "%s__%s" % (record_name(record), tail)


def _scene_download(record) -> str:
    """Where a package built in the scene is downloaded and kept: `$HIP/tex/`, never the library."""
    return os.path.join(hou.text.expandString("$HIP"), SCENE_DOWNLOADS, package_dirname(record))


@contextlib.contextmanager
def _download_folder(record):
    """A temporary folder for one record's download; it is removed with all it holds."""
    folder = tempfile.mkdtemp(prefix="amaze_download_")
    try:
        yield os.path.join(folder, package_dirname(record))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _downloaded_sources(folder: str, builder) -> list:
    """Each file downloaded into `folder` that `builder` does not read; the save copies the rest."""
    read = {os.path.normcase(os.path.normpath(hou.text.expandString(raw)))
            for _parm, raw in texstore.references(builder)}
    found = []
    for root, _dirs, names in os.walk(folder):
        found += [os.path.join(root, name) for name in names if not library_files.is_os_noise(name)
                  and os.path.normcase(os.path.normpath(os.path.join(root, name))) not in read]
    return sorted(found)


def _producer_for(record, source, resolution, dest, progress=None):
    """Download a record into `dest`, resolved to a Karma `produce` callback: (produce, note, error)."""
    name = record_name(record)
    if record.kind == "values":   # may download too: a measurement the shipped table lacks
        try:
            fetched_values = source.fetch(record, None, None, progress)
        except hou.OperationInterrupted:
            raise    # Esc is handled by the batch loop, not per record
        except Exception as exc:                        # noqa: BLE001
            debug.exception("measurement download", exc, uid=record.uid)
            return (None, "", "Could not read the measurement for %s: %s"
                    % (record.title, exc))
        values = fetched_values.get("values", {})
        if not values.get("color"):
            return (None, "", "%s has no usable measurement" % record.title)
        note = fetched_values.get("note", "")   # how derived numbers were derived; stored on the material

        def produce(builder):
            if values.get("complexIor"):   # measured metals become a conductor BSDF
                return _values_to_conductor_surface(values, builder)
            return _values_to_standard_surface(values, builder)

        return (produce, note, "")

    if os.path.isdir(dest) and os.listdir(dest):   # already downloaded: reused, never extracted over
        debug.event("import", "package already on disk - reusing",
                    dest=dest)
        found = matx_sources._find_mtlx(dest)    # the only function that finds the first .mtlx under a folder, also used after a new download
        if found:
            fetched = {"mtlx": found}
        else:
            return (None, "", "%s is already on disk but holds no "
                              ".mtlx - remove %s and try again"
                    % (record.title, dest))
    else:
        scratch = dest + ".downloading"   # fetched here, renamed to dest only once complete
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            fetched = source.fetch(record, resolution, scratch,
                                   progress=progress)
        except hou.OperationInterrupted:
            shutil.rmtree(scratch, ignore_errors=True)
            raise    # Esc is handled by the batch loop, not per record
        except Exception as exc:                        # noqa: BLE001
            debug.exception("download", exc, url=record.payload, dest=dest)
            shutil.rmtree(scratch, ignore_errors=True)
            return (None, "", "Download failed: %s" % exc)
        scratch_mtlx = (fetched or {}).get("mtlx")   # checked before the move, so a failure leaves dest unchanged
        if not scratch_mtlx or not os.path.exists(scratch_mtlx):
            shutil.rmtree(scratch, ignore_errors=True)
            debug.event("import", "download held no .mtlx - scratch "
                                  "dropped, destination untouched",
                        dest=dest)
            return (None, "", "No .mtlx document in the downloaded package")
        if os.path.isdir(scratch):
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)   # dest is empty here
            try:
                os.rename(scratch, dest)
            except OSError as exc:
                shutil.rmtree(scratch, ignore_errors=True)
                return (None, "", "The download could not be put in place: %s" % exc)
        fetched = {   # the fetch returned scratch paths; the files are at dest now
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
            debug.note(   # the only message about the effect; repair_mtlx_references reports the cause
                "%d of the textures for %s were not downloaded and "
                "could not be matched, so those inputs render black. "
                "The rest of the material came through."
                % (len(unresolved), name))

    def produce(builder):
        return matx_translate.build_material(mtlx_path, builder, name)

    return (produce, "", "")


def to_renderer(builder, scratch, name: str, renderer: str):
    """MaterialX's builder, or its `renderer` copy made in `scratch`: (builder, shader, wired, report)."""
    if renderers.normalized(renderer) == conversion_engine.INTERMEDIATE:
        return builder, None, None, None
    made = conversion_engine.convert(builder, conversion_engine.INTERMEDIATE, renderer, scratch, name)
    builder.destroy()
    if made.builder is not None:
        try:
            made.builder.setName(wording.sanitize_usd_path(name) or "material",
                                 unique_name=True)    # it was built beside the MaterialX one
        except hou.Error as exc:
            debug.event("import", "second builder not renamed", error=str(exc))
    report = made.report
    if report.skipped or report.approximated:
        debug.alert("\n".join(report.summary_lines()),
                    key=renderer.lower() + "-conversion")    # on screen: `note` shows nothing on Windows
    return made.builder, made.shader, made.wired, report


@contextlib.contextmanager
def _staged_build(record, source, resolution, dest, progress,
                  renderer):
    """Download into `dest`, build in a staging matnet, convert, warn: yields (builder, note, error)."""
    name = record_name(record)
    produce, note, error = _producer_for(
        record, source, resolution, dest, progress)
    if error:
        yield None, note, error
        return
    with hou.undos.disabler():    # the staging matnet is not recorded for undo ▸r/undo-groups
        scratch = hou.node("/obj").createNode("matnet")
    try:
        builder, shader, wired = nodes_mod.build_karma_material(
            scratch, name, produce)
        if shader is None:
            yield None, note, "Could not build a shading network for " + name
            return
        if renderers.normalized(renderer) != conversion_engine.INTERMEDIATE:    # every import is built in MaterialX first
            builder, shader, wired, _report = to_renderer(
                builder, scratch, name, renderer)
            if shader is None:
                yield None, note, "Could not convert %s to %s" % (
                    name, renderers.label(renderer))
                return
        if not wired:    # a warning on a success: the artist can wire it by hand
            debug.note(
                "\"%s\" was imported, but its surface output is not "
                "wired, so it renders black until it is connected."
                % name)
        yield builder, note, ""
    finally:
        try:
            with hou.undos.disabler():
                scratch.destroy()
        except (hou.OperationFailed, hou.ObjectWasDeleted):
            pass


def build_in_scene(record, source, resolution, destination,
                   progress=None, renderer: str = renderers.INTERMEDIATE.key,
                   path_style: str = "home"):
    """One online record built under `destination` in the scene, the library untouched: (builder, why)."""
    if destination is None:
        return (None, "No destination network for the material.")
    name = record_name(record)
    debug.event("import", "start to scene", title=record.title, name=name,
                source=record.source, kind=record.kind,
                destination=destination.path(), resolution=resolution)
    folder = _scene_download(record)
    with _staged_build(record, source, resolution, folder, progress,
                       renderer) as (builder, note, error):
        if error:
            return (None, error)
        moved = hou.moveNodesTo((builder,), destination)
        if not moved:
            return (None, "Could not move %s into %s"
                    % (name, destination.path()))
        builder = moved[0]
        texstore.write_paths_under(builder, folder, helpers.houdini_path, path_style)    # Write Paths As
        helpers.auto_place(builder)
        if destination.type().name() == "materiallibrary":   # registered, or it may not render
            nodes_mod.register_in_materiallibrary(destination, builder)
        try:
            comment = _credit_text(record, source)   # the node comment holds credit and licence
            if record.licence:
                comment += "\nLicense: %s" % record.licence
            if note:
                comment += "\n\n%s" % note
            builder.setComment(comment)
        except hou.Error as exc:
            debug.event("import", "comment not set", error=str(exc))
        debug.event("import", "built in scene", name=name,
                    path=builder.path())
        return (builder, "")


def hosted_picture(record, source, renderer) -> str:
    """Amaze's own render of `record` in a temp file, for a MaterialX import; empty when none."""
    if renderers.normalized(renderer) != conversion_engine.INTERMEDIATE:
        return ""
    if not (getattr(record, "payload", None) or {}).get("preview"):
        return ""
    folder = tempfile.mkdtemp(prefix="amaze_hosted_picture_")
    path = os.path.join(folder, "picture.jpg")
    try:
        source.read_thumb_to(record, path)
    except Exception as exc:                            # noqa: BLE001
        shutil.rmtree(folder, ignore_errors=True)
        debug.event("import", "hosted picture not read - rendering instead",
                    title=record.title, error=str(exc))
        return ""
    return path


def import_record(record, source, resolution, library, preferences,
                  progress=None, renderer: str = renderers.INTERMEDIATE.key, *, save, render=True):
    """One record and its download saved by `save` into `library`: (ok, why); why names it if unlisted."""
    name = record_name(record)
    debug.event("import", "start", title=record.title, name=name,
                source=record.source, kind=record.kind,
                category=record.category, resolution=resolution)
    with hou.undos.disabler(), _download_folder(record) as dest, \
            _staged_build(record, source, resolution, dest, progress,
                          renderer) as (builder, measurement_note, error):    # all scratch ▸r/undo-groups
        if error:
            return (False, error)
        picture = hosted_picture(record, source, renderer)
        sources = _downloaded_sources(dest, builder)    # the save copies each file the network reads
        save(   # the new row is found by its stamped id, never by position
            builder,
            record.category,
            ",".join(record.tags or []),
            False,
            **({"picture": picture} if picture else {}),
            **({"sources": sources} if sources else {}),
            **({} if render else {"render": False}),    # its caller renders the batch once
        )
        if picture:
            shutil.rmtree(os.path.dirname(picture), ignore_errors=True)
        stamped = builder.userData("assetlib_id") or ""
        row = library.find_asset_row_by_id(stamped) if stamped else -1
        if row == -1:
            return (False, "%s could not be saved to your library, so "
                           "it was not added. Your scene is unchanged."
                           % name)
        listed = True    # unknown when crediting raises: the library has already shown its own alert
        try:
            credited = library.assets[row]
            credited.license = record.licence or ""
            extra = credited._extra
            extra["source"] = record.source or ""    # where it came from and which one, on the row
            extra["online_uid"] = str(record.uid or "")    # not `uid`: that spelling is the pre-connector id, which packages.py strips on import
            listed = library.save()    # writes the whole database: an earlier failed save is written here too
            from amaze.core import notes
            notes.set_note(preferences, notes.note_key(library.NOTES_SECTION, stamped), [
                {"t": "text", "text": text}
                for text in (_credit_text(record, source), measurement_note) if text])    # ▸p/d03-retired
        except Exception as exc:
            debug.exception("credit the import", exc)
            debug.event("import", "credit not written", error=str(exc))
        debug.event("import", "registered", name=name,
                    rows=library.rowCount(), listed=listed)
        return (True, "" if listed else name)    # ok with a name: the asset was saved, but its database was not
