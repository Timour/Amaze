"""The online import: catalogue records into the library or the scene, for one panel."""

import contextlib
import functools

import hou

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.core import debug, library, matx_sources, renderers
from amaze.render import nodes


class OnlineImport:
    """One panel's online import doors; the panel holds it as `online_import`."""

    def __init__(self, panel) -> None:
        self.panel = panel

    @contextlib.contextmanager
    def download_operation(self, records):
        """The interruptable operation around a multi-record import; yields progress_for(i, name)."""
        total = max(len(records), 1)
        self.panel._online_download_active = True    # a late preview signal must not repaint the bar
        try:
            with hou.InterruptableOperation(    # type: ignore
                messages.IMPORTING_ONLINE_MATERIALS, open_interrupt_dialog=True
            ) as op:
                def progress_for(i, name=""):
                    def on_progress(frac):
                        frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
                        op.updateLongProgress((i + frac) / total,
                                              "%d/%d  %s" % (i + 1, total, name))
                    return on_progress
                yield progress_for
        finally:
            self.panel._online_download_active = False

    def import_records(self, records, renderer=renderers.HUB.key) -> None:
        """Import online records into the LIBRARY, built as `renderer` through the conversion engine."""
        if not len(records):
            return
        total = len(records)
        failures, unlisted = [], []
        held = {str(mat.mat_id) for mat in getattr(self.panel.material_model, "assets", ())}
        with self.download_operation(records) as progress_for:
            for i, rec in enumerate(records):
                on_progress = progress_for(i, rec.title)
                try:    # one bad record must not abandon the batch
                    ok, reason = self.import_material(
                        rec, on_progress=on_progress, renderer=renderer, render=False
                    )
                except hou.OperationInterrupted:
                    debug.status(messages.ONLINE_IMPORT_STOPPED % (i, total))
                    break
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("online import", exc, record=rec.title)
                    ok, reason = False, str(exc)
                if not ok:
                    failures.append("%s: %s" % (rec.title, reason))
                elif isinstance(reason, library.ListNotSaved):
                    unlisted.append(str(reason))
        if self.panel.material_model is not None:
            self.panel.render_landed(held)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:    # ONE dialog for the batch, never one per record
            ui.displayMessage(
                messages.AMAZE_COULD_NOT % (len(failures), total),
                details="\n".join(failures[:10]),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        library.say_unlisted(unlisted)    # the status line, last: nothing after it writes the line

    def import_material(self, record, on_progress=None,
                        renderer=renderers.HUB.key, render=True):
        """Download and save one online material as `renderer`, calling on_progress(0..1): (ok, reason)."""
        from amaze.core import matx_import
        if record is None or not self.panel.material_model:
            return (False, messages.NO_LIBRARY_TO_IMPORT_INTO)
        source, resolution, error = self.source_for(record)
        if error:
            return (False, error)
        if source is None:
            return (False, messages.ONLINE_SOURCE_UNKNOWN)
        if getattr(record, "kind", "") == "amazepkg":
            return self.panel.package_import.import_record(
                record, source, restore=False, on_progress=on_progress)
        ok, reason = matx_import.import_record(    # NO layout pair: it ends in add_asset, an insert
            record, source, resolution, self.panel.material_model, self.panel.prefs,
            progress=on_progress, renderer=renderer,
            save=functools.partial(material_actions.add_asset, self.panel.material_model),
            render=render,    # False: the caller renders its batch once
        )
        if not ok:
            return (False, reason or messages.ONLINE_IMPORT_FAILED)
        self.panel.category_model.check_add_category(record.category)    # no relayout wrapper: it announces its own insert
        self.panel.refresh_sidebar_categories()
        return (True, library.ListNotSaved(reason) if reason else "")    # a name: landed, unlisted

    def source_for(self, record):
        """The record's source and the resolution to fetch it at: (source, resolution, error)."""
        source = self.panel.matx_online_model.source_for(record)
        if source is None:
            return (None, None, messages.ONLINE_SOURCE_UNKNOWN_NAMED % record.source)
        if not source.needs_download(record):    # ask the source; sources override it
            return (source, None, "")     # nothing to download
        if record.kind in ("values", "amazepkg"):
            return (source, None, "")     # downloads, but picks no resolution
        resolution = matx_sources.pick_resolution(
            source.resolutions(record), self.panel.prefs.matx_resolution
        )
        if resolution is None:
            return (None, None,
                    messages.NO_DOWNLOADABLE_PACKAGE % record.title)
        return (source, resolution, "")

    def import_records_to_scene(self, records,
                                renderer=renderers.HUB.key) -> None:
        """Build online records into the scene, not the library; store tiles go to the library."""
        from amaze.core import matx_import
        packages_only = [r for r in records
                         if getattr(r, "kind", "") == "amazepkg"]
        if packages_only:
            self.import_records(packages_only)
            records = [r for r in records
                       if getattr(r, "kind", "") != "amazepkg"]
        total = len(records)
        if not total:
            return
        built, failures, last, stopped_after = [], [], None, None
        ui = getattr(hou, "ui", None)
        with self.download_operation(records) as progress_for:
            with hou.undos.group("Amaze Import to Scene"):    # one undo step, the destination included
                destination = nodes.karma_destination(self.panel.prefs)
                if destination is None:
                    if ui is not None:
                        ui.displayMessage(
                            messages.NO_MATERIAL_DESTINATION_NETWORK,
                            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                        )
                    return
                for i, rec in enumerate(records):
                    source, resolution, error = self.source_for(rec)
                    if error:
                        failures.append("%s: %s" % (rec.title, error))
                        continue
                    on_progress = progress_for(i, rec.title)

                    try:
                        builder, reason = matx_import.build_in_scene(
                            rec, source, resolution, destination, self.panel.prefs,
                            progress=on_progress, renderer=renderer,
                        )
                    except hou.OperationInterrupted:
                        stopped_after = i
                        break
                    except Exception as exc:           # noqa: BLE001
                        debug.exception("import to scene", exc,
                                        title=rec.title)
                        builder, reason = None, str(exc)    # one bad record must not abandon the batch
                    if builder is None:
                        failures.append("%s: %s" % (rec.title, reason))
                        continue
                    built.append(builder.name())
                    last = builder
                if last is not None:
                    last.setCurrent(True, True)    # fronts the new material
        debug.event("import", "to scene finished", built=len(built),
                    failed=len(failures), stopped_after=stopped_after)
        if ui is not None and failures:
            ui.displayMessage(
                messages.SCENE_BUILD_PARTIAL_FAILURE % (len(failures), total),
                details="\n".join(failures[:10]),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        elif ui is not None and last is not None and stopped_after is None:
            ui.setStatusMessage(
                "Amaze: %s in %s" % (", ".join(built[:3]),
                                     last.parent().path())
            )
        if stopped_after is not None:
            debug.status(messages.ONLINE_IMPORT_STOPPED % (stopped_after, total))
