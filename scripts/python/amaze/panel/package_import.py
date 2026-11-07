"""The package import: `.amazepkg` files and store tiles into the library, for one panel."""

import os

import hou

from amaze import messages
from amaze.core import debug, locations
from amaze.helpers import hostos
from amaze.panel import sections


class PackageImport:
    """One panel's package import doors; the panel holds it as `package_import`."""

    def __init__(self, panel) -> None:
        self.panel = panel

    def import_file(self, path: str, restore: bool = False) -> dict:
        """Import a whole package; `restore=True` keeps original ids. Answers the core summary."""
        from amaze.core import packages
        summary = packages.import_package(self.models(),
                                          self.panel.prefs, path,
                                          restore=restore)
        self.absorb_summary(summary)
        return summary

    def import_package(self) -> None:
        """Package Import: the picker, the import, then one summary; no dialog when headless."""
        from amaze.core import packages
        ui = getattr(hou, "ui", None)
        if not self.panel.prefs.dir:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED)
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
                ui.displayMessage(str(exc))
            return
        if ui is not None:
            ui.displayMessage(
                messages.PACKAGE_IMPORT_SUMMARY % (summary["imported"], summary["files"]))

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
            model = getattr(self.panel, attr, None) if attr else None
            if model is not None and getattr(cls, "key", "") != "file":
                models[cls.key] = model
        return models

    def absorb_summary(self, summary) -> None:
        """Register a package import's categories on their sidebars, and its import folder."""
        for key, names in summary.get("categories", {}).items():
            section = self.panel.sections.get(key)
            st = section.stack() if section is not None else None
            if st is None:
                continue
            for name in sorted(names):
                st.categories.check_add_category(name)
        if summary.get("files"):
            folder = hostos.canonical_path_key(
                os.path.join(self.panel.prefs.dir, "import"))
            folders = getattr(self.panel, "file_folders_model", None)
            listed = {hostos.canonical_path_key(path)
                      for path in self.panel.prefs.file_folders}
            if folder not in listed:
                self.panel.prefs.set_file_folder_name(folder, "Import")    # before the row lands, and only here: a rename stays
                self.panel.prefs.set_file_folder_kinds(folder, locations.EVERY_KIND)
                if folders is None:
                    self.panel.prefs.add_file_folder(folder)
                else:
                    folders.add_folder(folder)
            elif folders is not None:
                folders.refresh_counts()    # already listed: files landed in it, so its number moved
                row = folders.row_of(folder)
                if row is not None:
                    folders.dataChanged.emit(folders.index(0),
                                             folders.index(row))

    def import_record(self, record, source, restore,
                      on_progress=None):
        """One store tile into the library, fresh or restore: (ok, reason); `on_progress` pumps the UI."""
        from amaze.core import packages
        url = record.payload.get("package")
        debug.event("import", "package tile start", title=record.title,
                    package=str(url), restore=bool(restore))
        self.panel._last_package_summary = None    # the restore batch reads its totals here
        try:
            entry = record.payload.get("entry")
            if not entry:
                return (False, messages.STORE_TILE_HAS_NO_ENTRY)
            notify = None if on_progress is None else (
                lambda done, total:
                on_progress(min(done / float(max(total, 1)), 1.0)))
            bundle = source.import_reader(url, notify=notify)    # its own: a preview may hold the shared one
            summary = packages.import_entries(
                self.models(), self.panel.prefs, bundle, [entry],
                restore=restore)
            self.panel._last_package_summary = summary
            self.absorb_summary(summary)
            if on_progress is not None:
                on_progress(1.0)
            if summary.get("refused"):
                return (False, "; ".join(summary.get("problems") or ())
                               or messages.STORE_TILE_NOT_IMPORTED)
            if restore and summary.get("skipped"):
                return (True, "")
            if not summary.get("imported") and not summary.get("files"):
                return (False, messages.STORE_TILE_IMPORTED_NOTHING)
            return (True, "")
        except Exception as exc:                          # noqa: BLE001
            debug.exception("package import", exc, record=record.title)
            return (False, str(exc))

    def restore(self, records) -> dict:
        """Restore the selected store tiles by original id, with one summary for the batch."""
        totals = {"imported": 0, "skipped": 0, "files": 0, "refused": 0}
        failures = []
        with self.panel.online_import.download_operation(records) as progress_for:
            for i, record in enumerate(records):
                source, _resolution, error = self.panel.online_import.source_for(
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
                summary = self.panel._last_package_summary or {}
                for key in totals:
                    totals[key] += summary.get(key, 0)
                if not ok and reason:
                    failures.append("%s: %s" % (record.title, reason))
        ui = getattr(hou, "ui", None)
        if ui is not None:
            lines = [messages.STORE_RESTORE_SUMMARY
                     % (totals["imported"], totals["skipped"])]
            if failures:
                lines += [""] + failures[:10]
            ui.displayMessage("\n".join(lines))
        return totals
