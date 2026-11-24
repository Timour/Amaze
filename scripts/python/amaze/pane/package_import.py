"""The package import: `.amazepkg` files and store tiles into the library, for one pane."""

import os

import hou

from amaze import messages
from amaze.core import debug
from amaze.helpers import hostos
from amaze import sections
class PackageImport:
    """One pane's package import commands; the pane holds it as `package_import`."""

    def __init__(self, pane) -> None:
        self.pane = pane
        self.last_summary = None    # the last store tile's summary; the restore batch reads its totals

    def import_file(self, path: str, restore: bool = False) -> dict:
        """Import a whole package; `restore=True` replaces curated presets. Returns packages' summary."""
        from amaze.core import packages
        summary = packages.import_package(self.models(),
                                          self.pane.prefs, path,
                                          restore=restore)
        self.register_imported_categories(summary)
        return summary

    def import_package(self) -> None:
        """Package Import: the picker, the import, then one summary; no dialog when headless."""
        from amaze.core import packages
        ui = getattr(hou, "ui", None)
        if not self.pane.prefs.dir or getattr(self.pane, "material_model", None) is None:
            if ui is not None:    # no library open, whether none is set or it was left closed
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        picked = ui.selectFile(
            title="Import Amaze Package",
            file_type=hou.fileType.Any,
            pattern="*" + packages.SUFFIX,
            chooser_mode=hou.fileChooserMode.Read,
        ) if ui is not None else ""
        picked = (picked or "").strip()
        if not picked:
            return
        try:
            summary = self.import_file(
                hou.text.expandString(picked))
        except packages.PackageError as exc:
            if ui is not None:
                ui.displayMessage(str(exc),
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        if ui is not None:
            held_back = summary.get("refused") or summary.get("skipped")    # the reasons go in the details
            ui.displayMessage(
                messages.PACKAGE_IMPORT_SUMMARY % (summary["imported"], summary["files"]),
                details="\n".join((summary.get("problems") or [])[:10]), title=messages.TITLE_AMAZE,
                severity=hou.severityType.Warning if held_back else hou.severityType.Message)

    def ask_destination(self) -> str:
        """The `.amazepkg` export path, suffix ensured; "" when headless or cancelled."""
        from amaze.core import packages
        ui = getattr(hou, "ui", None)
        if ui is None:
            return ""
        picked = ui.selectFile(
            title="Export Amaze Package",
            file_type=hou.fileType.Any,
            pattern="*" + packages.SUFFIX,
            default_value="package" + packages.SUFFIX,
            chooser_mode=hou.fileChooserMode.Write,
        )
        picked = (picked or "").strip()
        if not picked:
            return ""
        picked = hou.text.expandString(picked)
        if not picked.endswith(packages.SUFFIX):
            picked += packages.SUFFIX
        return picked

    def models(self) -> dict:
        """{section key: library model} for every asset section that has one."""
        models = {}
        for cls in sections.SECTION_CLASSES:
            attr = getattr(cls, "model_attr", "")
            model = getattr(self.pane, attr, None) if attr else None
            if model is not None and getattr(cls, "key", "") != "file":
                models[cls.key] = model
        return models

    def register_imported_categories(self, summary) -> None:
        """Register a package import's categories on their sidebars, and its import folder."""
        for key, names in summary.get("categories", {}).items():
            section = self.pane.sections.get(key)
            st = section.stack() if section is not None else None
            if st is None:
                continue
            for name in sorted(names):
                st.categories.check_add_category(name)
        if summary.get("files"):
            folder = hostos.canonical_path_key(
                os.path.join(self.pane.prefs.dir, "import"))
            folders = getattr(self.pane, "file_folders_model", None)
            listed = {hostos.canonical_path_key(path)
                      for path in self.pane.prefs.file_folders}
            if folder not in listed:
                self.pane.prefs.set_file_folder_name(folder, "Import")    # before the row is added, and only here: a user rename is kept
                if folders is None:
                    self.pane.prefs.add_file_folder(folder)
                else:
                    folders.add_folder(folder)
            elif folders is not None:
                folders.refresh_counts()    # already listed: files were added to it, so its count changed
                row = folders.row_of(folder)
                if row is not None:
                    folders.dataChanged.emit(folders.index(0),
                                             folders.index(row))

    def import_record(self, record, source, restore,
                      on_progress=None):
        """Import one store tile, new or restored: (ok, reason); `on_progress` updates the UI."""
        from amaze.core import packages
        url = record.payload.get("package")
        debug.event("import", "package tile start", title=record.title,
                    package=str(url), restore=bool(restore))
        self.last_summary = None
        try:
            entry = record.payload.get("entry")
            if not entry:
                return (False, messages.STORE_TILE_HAS_NO_ENTRY)
            notify = None if on_progress is None else (
                lambda done, total:
                on_progress(min(done / float(max(total, 1)), 1.0)))
            bundle = source.import_reader(url, notify=notify)    # a separate reader: a preview may be using the shared one
            summary = packages.import_entries(
                self.models(), self.pane.prefs, bundle, [entry],
                restore=restore)
            self.last_summary = summary
            self.register_imported_categories(summary)
            if on_progress is not None:
                on_progress(1.0)
            if summary.get("refused"):
                return (False, "; ".join(summary.get("problems") or ())
                               or messages.STORE_TILE_NOT_IMPORTED)
            if not summary.get("imported") and not summary.get("files"):
                return (False, messages.STORE_TILE_IMPORTED_NOTHING)
            return (True, "")
        except hou.OperationInterrupted:
            raise    # Esc stops the whole batch loop, not only this tile
        except Exception as exc:                          # noqa: BLE001
            debug.exception("package import", exc, record=record.title)
            return (False, str(exc))

    def restore(self, records) -> dict:
        """Restore the selected store tiles, each replacing its preset, with one summary for the batch."""
        totals = {"imported": 0, "replaced": 0, "files": 0, "refused": 0}
        failures = []
        with self.pane.online_import.download_operation(records) as progress_for:
            for i, record in enumerate(records):
                source, _resolution, error = self.pane.online_import.source_for(
                    record)
                if error or source is None:
                    failures.append("%s: %s" % (record.title,
                                                error or messages.ONLINE_SOURCE_UNKNOWN))
                    continue
                try:
                    ok, reason = self.import_record(
                        record, source, restore=True,
                        on_progress=progress_for(i, record.title))
                except hou.OperationInterrupted:
                    debug.status(messages.ONLINE_IMPORT_STOPPED % (i, len(records)))
                    break
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("package restore", exc,
                                    record=record.title)
                    failures.append("%s: %s" % (record.title, exc))
                    continue
                summary = self.last_summary or {}
                for key in totals:
                    totals[key] += summary.get(key, 0)
                if not ok and reason:
                    failures.append("%s: %s" % (record.title, reason))
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(
                messages.STORE_RESTORE_SUMMARY % (totals["imported"], totals["replaced"]),
                details="\n".join(failures[:10]), title=messages.TITLE_AMAZE,
                severity=hou.severityType.Warning if failures else hou.severityType.Message)
        return totals
