"""Opening the pane's library: the checks, the models built or switched, and updates."""

import functools
import os
import threading
import types

from PySide6 import QtCore
import hou

import amaze
from amaze import messages
from amaze.actions import files as files_actions
from amaze.actions import library as library_actions
from amaze.actions import materials as material_actions
from amaze.core import (category, debug, documents, gradient_library, library_db,
                        library_files, locations, matx_library, model_registry,
                        multifilterproxy_model, texstore, texture_library, users)
from amaze.helpers import hostos
from amaze import sections
from amaze.sections import online as online_section
_FOLDERS_GIVEN_ICONS = globals().get("_FOLDERS_GIVEN_ICONS", set())    # library folders given their icon this session


def _give_folder_icons(library_dir: str) -> None:
    """The library folder and its `materials` folder each shown with their own icon."""
    hostos.give_folder_icon(library_dir, amaze.package_file("ui", "library_folder"))
    hostos.give_folder_icon(os.path.join(library_dir, library_files.SECTION_FOLDERS[
        library_files.MATERIALS]), amaze.package_file("ui", "matx_folder"))


def _flush_saves_on_close(schedule, *_destroyed) -> None:
    """On pane close: drop its save timer and save every pending change now."""
    library_db.drop_scheduler(schedule)
    library_db.flush()


class Library:
    """Every way onto a library, one sequence; the pane holds it as `library`. ▸o/section-api"""

    def __init__(self, pane) -> None:
        self.pane = pane
        self.models_dir = None    # the library the models use, for closing Preferences and for a Cancel
        self.models_user = ""    # the user they show the stars and locations of
        self._conversion_for = ("", "")    # the folder and user the waiting conversion offer is for
        self._save_timer = None

    def start(self) -> bool:
        """The library at the pane's start, its dialogs deferred; False when no settings were read."""
        prefs = self.pane.prefs
        if not self.pane.prefs_loaded:
            self._open_libraryless()
            return False
        if (library_actions.index_unreadable(prefs.dir)
                or library_actions.folder_not_empty_without_library(prefs.dir)):
            self._open_later()    # a dialog opened during the build blocks the pane
            opened = False    # the pane opens without a library; its dialog comes later
        else:
            opened = self._open_at_start()
        if not opened:
            self._open_libraryless()    # still a finished construction, so `panel ready` is logged
        return True

    def _open_libraryless(self) -> None:
        """The no-library shape: every model attribute present and None, so the gear still works."""
        pane = self.pane
        pane.material_model = None
        pane.category_model = None
        pane.cop_model = None    # a right-click save reads every model before one is built
        pane.cop_category_model = None
        pane.code_model = None
        pane.code_category_model = None
        pane.file_files_model = None    # Preferences reads it through the pane, and takes None
        pane.file_folders_model = None
        pane.matx_online_model = None    # setup() builds the online world; `enter_online` refuses without it
        pane.online_changed.emit()

    def _open_later(self) -> None:
        """Open the library once Qt is idle, so its dialog can draw. ▸r/modal-in-pane-build"""
        timer = self._open_library_timer = QtCore.QTimer(self.pane)    # owned, so it is deleted with the pane
        timer.setSingleShot(True)
        timer.setInterval(0)
        timer.timeout.connect(self._open_at_start)
        timer.start()

    def _open_at_start(self) -> bool:
        """Open the library only once this computer's user is set; `ensure_library_user` prompts."""
        return self.open_library()

    def serves(self, folder: str) -> bool:
        """Whether the models are open on `folder`."""
        return (getattr(self.pane, "material_model", None) is not None
                and hostos.comparable_path(str(self.models_dir or ""))
                == hostos.comparable_path(str(folder or "")))

    def _repaired(self, folder: str) -> bool:
        """Offer a repair of `folder`'s unreadable index; True once the chosen fix makes it read."""
        from amaze.dialogs import check_dialog
        switching = getattr(self.pane, "material_model", None) is not None    # a library is open
        debug.event("session", "library index unreadable", dir=folder, switching=switching)
        ui = getattr(hou, "ui", None)
        if ui is None:
            return False
        choice = ui.displayMessage(
            messages.LIBRARY_INDEX_UNREADABLE_SWITCHING if switching
            else messages.LIBRARY_INDEX_UNREADABLE,
            buttons=messages.BUTTONS_REPAIR_OR_CANCEL if switching
            else messages.BUTTONS_REPAIR_OR_OPEN_WITHOUT,
            severity=hou.severityType.Warning,
            default_choice=0, close_choice=1,
            title=messages.TITLE_AMAZE)
        if choice != 0:
            debug.event("session", "index repair declined")
            return False
        check_dialog.repair_failed(folder, self.pane.prefs)    # the user picks the fix there
        if library_actions.index_unreadable(folder):
            debug.event("session", "index still unreadable after Check Library", dir=folder)
            ui.displayMessage(messages.DATABASE_STILL_UNREADABLE_SWITCHING if switching
                              else messages.DATABASE_STILL_UNREADABLE,
                              severity=hou.severityType.Warning, title=messages.TITLE_AMAZE)
            return False
        debug.event("session", "index repaired", dir=folder)
        return True

    def reload(self) -> None:
        """Reload Library: save, re-read the settings, then open the library they name."""
        pane = self.pane
        if not pane.material_model or not pane.category_model:
            return
        pane.material_model.save()
        pane.prefs.load()
        self.open_library()

        debug.event("session", "library reloaded")

    def takes_library(self, folder: str) -> bool:
        """Accept a picked folder only once its index reads: Repair first, or nothing is written."""
        if library_actions.folder_not_empty_without_library(folder):
            debug.event("session", "library not opened - the folder is not empty and holds no library", dir=folder)
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    messages.LIBRARY_FOLDER_NOT_EMPTY,
                    severity=hou.severityType.Warning,
                    title=messages.TITLE_AMAZE)
            return False
        return not library_actions.index_unreadable(folder) or self._repaired(folder)

    def open_library(self) -> bool:
        """Every library opening runs these steps in this order; False when it stays closed."""
        prefs = self.pane.prefs
        refused = library_actions.index_unopenable(prefs.dir)
        if refused:    # first: every later step reads the library's database
            return self._stay_closed(refused)
        if self._library_too_new():
            return self._stay_closed()    # the update is offered once Qt is idle
        if users.current(prefs) is None:    # no library opens, converts or is set up without one
            debug.event("session", "library not opened - no user picked", dir=prefs.dir)
            return self._stay_closed()    # it is opened from Preferences, where its user is picked
        if self._library_to_convert():
            return self._stay_closed()    # the conversion is offered once Qt is idle
        if (library_actions.index_unreadable(prefs.dir)
                and not self._repaired(prefs.dir)):
            return self._stay_closed()
        library_actions.prepare(prefs)
        if not library_actions.index_present(prefs.dir):    # prepare could not set one up
            return self._stay_closed()
        why = self._open_models()
        if why:
            return self._stay_closed(why)
        texstore.publish_env(prefs)    # $AMAZELIB is set to the library the models now use
        self._update_library()    # before any tile paints
        self._seed_curated_content()    # once per library, marker-guarded
        if prefs.note_library_opened(prefs.dir):
            prefs.save()    # the Library list, the most recently opened first
        if hou.isUIAvailable() and prefs.dir not in _FOLDERS_GIVEN_ICONS:    # once a session, off the UI thread
            _FOLDERS_GIVEN_ICONS.add(prefs.dir)
            threading.Thread(target=_give_folder_icons, daemon=True, args=(prefs.dir,)).start()
        return True

    def reread_settings(self) -> bool:
        """Preferences applied: read the settings again, and open the library if it is another."""
        prefs = self.pane.prefs
        prefs.load()    # the debug log and the cache folder follow on Apply, where they change
        switched = prefs.dir != self.models_dir
        if switched:    # only a library the models do not hold yet gets a full re-read
            self.open_library()
        elif str(prefs.library_user or "") != self.models_user:    # the same library, another user
            self._user_switched()
        return switched

    def _user_switched(self) -> None:
        """Each model showing one user's rows, stars or locations, reads them for the user now current."""
        self.models_user = str(self.pane.prefs.library_user or "")
        shown = list(self.models())
        for section in self.pane.sections.values():
            tiles = section.tile_models()[0]
            if tiles is not None and tiles not in shown:
                shown.append(tiles)
        for model in shown:
            changed = getattr(model, "user_changed", None)
            if changed is not None:
                changed()

    def _open_models(self) -> str:
        """The models' step of `open_library`: "" once they use `prefs.dir`, else the reason."""
        prefs = self.pane.prefs
        try:
            if getattr(self.pane, "material_model", None) is None:
                self.setup()    # with no library open there are no models to switch
            else:
                self.switch_all_models()
        except (OSError, ValueError, KeyError) as exc:    # an index that exists but cannot be opened
            debug.exception("library open", exc, dir=prefs.dir)
            return (library_actions.index_unopenable(prefs.dir)
                    or messages.LIBRARY_LIST_NOT_LOADED % exc)
        return ""

    def _stay_closed(self, why: str = "") -> bool:
        """False; an open library stays open, its folder and user put back, `why` shown."""
        prefs = self.pane.prefs
        switching = getattr(self.pane, "material_model", None) is not None
        if library_db.key_of(prefs) != library_db.key_of(
                types.SimpleNamespace(dir=self.models_dir or "")):
            library_db.release(prefs)    # read during the checks, never opened: released
        if switching:    # put back what Reload or Apply changed
            prefs.dir, prefs.library_user = self.models_dir, self.models_user
            prefs.save()
            debug.event("session", "previous library left open", dir=prefs.dir)
        if why:    # `debug.refuse` defers it: a modal in the pane's build draws black ▸r/modal-in-pane-build
            debug.refuse(debug.Damage(messages.LIBRARY_NOT_OPENED_SWITCHING % why if switching
                                      else messages.LIBRARY_NOT_OPENED % why))
        return False

    def _note_models_library(self) -> None:
        """Record the library and user the models now use, for closing Preferences and for a Cancel."""
        self.models_dir = self.pane.prefs.dir
        self.models_user = str(self.pane.prefs.library_user or "")

    def models(self) -> tuple:
        """Every library-backed model that exists now, from each section's `library_model_attrs`."""
        found = []
        for section in self.pane.sections.values():
            for attr in getattr(section, "library_model_attrs", ()):
                model = getattr(self.pane, attr, None)
                if model is not None and model not in found:
                    found.append(model)
        return tuple(found)

    def switch_all_models(self) -> None:
        """The models' step of `open_library`: every library-backed model re-pointed at `prefs.dir`."""
        pane = self.pane
        pane.library_switching.emit()    # a pending comment is saved to its own library first
        library_db.flush()    # pending saves are written to the library they were made in
        library_db.refresh()    # a switch reads every database as it is on disk now
        locations.forget()
        models = self.models()
        if not models:
            return
        pane.prefs.load()    # the switch's one read of the settings; every model takes this Prefs
        for m in model_registry.sidebars_first(models):    # each resets itself; no layout pair around a reset
            m.preferences = pane.prefs    # a shared model may hold another pane's ▸p/one-model-set
            m.switch_model_data()
        model_registry.rebind(pane.prefs, pane.material_model)    # the shared set, re-registered under its library
        pane.library_switched.emit()
        self._note_models_library()
        debug.event("session", "library switched", dir=self.models_dir)
        section = pane.active_section()
        if section is not None:
            section.library_switched()

    def _update_library(self) -> None:
        """Update the library to this Amaze's version before any tile paints, with no prompt."""
        try:
            if library_actions.update(self.pane.prefs):
                self.pane.library_updated.emit()
        except Exception as exc:                          # noqa: BLE001 - never blocks the pane
            debug.exception("library update", exc)

    def _library_too_new(self) -> bool:
        """A library a newer Amaze updated is not opened; the update is offered once Qt is idle."""
        from amaze.core import library_policy
        found = library_actions.newer_version(self.pane.prefs)
        if not found:
            return False
        debug.event("session", "library is newer than this Amaze - not opened",
                    found=found, known=library_policy.LIBRARY_VERSION)
        timer = getattr(self, "_update_offer_timer", None)
        if timer is None:    # owned, so it is deleted with the pane ▸r/model-parent
            timer = self._update_offer_timer = QtCore.QTimer(self.pane)
            timer.setSingleShot(True)
            timer.setInterval(0)    # a modal inside onCreateInterface draws black
            timer.timeout.connect(self._offer_amaze_update)
        timer.start()
        return True

    def _library_to_convert(self) -> bool:
        """A 2.0 library is not opened; converting it to 3.0 is offered once Qt is idle."""
        from amaze.core import layout_conversion
        prefs = self.pane.prefs
        if not layout_conversion.needs_conversion(str(prefs.dir or "")):
            return False
        debug.event("session", "library is 2.0 - not opened until converted", dir=prefs.dir)
        self._conversion_for = (str(prefs.dir), str(prefs.library_user or ""))    # `_stay_closed` resets prefs
        timer = getattr(self, "_convert_offer_timer", None)
        if timer is None:    # owned, so it is deleted with the pane ▸r/model-parent
            timer = self._convert_offer_timer = QtCore.QTimer(self.pane)
            timer.setSingleShot(True)
            timer.setInterval(0)    # a modal inside onCreateInterface draws black
            timer.timeout.connect(self._offer_conversion)
        timer.start()
        return True

    def _offer_conversion(self) -> None:
        """Convert or Cancel, for the 2.0 library left closed: that one converted and opened."""
        from amaze.core import layout_conversion, library_settings
        folder, user = self._conversion_for
        ui = getattr(hou, "ui", None)
        if ui is None or ui.displayMessage(
                messages.LIBRARY_NEEDS_CONVERSION, buttons=messages.BUTTONS_CONVERT_LIBRARY,
                default_choice=1, close_choice=1, severity=hou.severityType.Warning,
                title=messages.TITLE_AMAZE) != 0:
            return
        offered = types.SimpleNamespace(dir=folder, library_user=user)
        try:
            layout_conversion.convert(library_db.guard_of(offered), user)
        except OSError as exc:
            debug.event("library", "conversion to 3.0 failed", dir=folder, error=str(exc))
            ui.displayMessage(messages.LIBRARY_CONVERSION_FAILED % exc, title=messages.TITLE_AMAZE,
                              severity=hou.severityType.Error)
            return
        library_settings.stamp_version(offered)
        prefs = self.pane.prefs
        prefs.dir, prefs.library_user = folder, user
        prefs.save()    # the open re-reads the settings
        self.open_library()

    def _offer_amaze_update(self) -> None:
        """Update Amaze or Cancel, for the library left closed; headless, no dialog is shown."""
        from amaze.core import library_settings
        from amaze.dialogs import update_dialog
        ui = getattr(hou, "ui", None)
        if ui is None:
            return
        library_dir = str(self.pane.prefs.dir or "")
        if ui.displayMessage(
                messages.LIBRARY_NEEDS_NEWER_AMAZE % library_settings.version_label(
                    library_settings.library_formats(library_dir)),
                buttons=messages.BUTTONS_UPDATE_AMAZE, default_choice=0, close_choice=1,
                severity=hou.severityType.Warning, title=messages.TITLE_AMAZE) != 0:
            return
        update_dialog.check_and_install(library_dir, offer=False)    # Update Amaze was the offer

    def _seed_curated_content(self) -> None:
        """Add the shipped starters, on construction and on a switch. ▸archive/actions/library.py"""
        pane = self.pane
        code_model = getattr(pane, "code_model", None)    # with no library open the models are None
        gradient_model = getattr(pane, "gradient_model", None)
        library_actions.seed_starters(
            code_model, pane.code_category_model if code_model is not None else None,
            gradient_model, pane.gradient_categories_model if gradient_model is not None else None)

    def ensure_library_user(self) -> str:
        """After the first paint: this computer's user, or a prompt to open Preferences."""
        preferences = self.pane.prefs
        uid = users.current(preferences)
        if uid or not library_actions.index_present(preferences.dir):
            return uid or ""    # no library: the pane's empty state shows where to set one
        debug.event("users", "no user picked for this library", dir=preferences.dir)
        ui = getattr(hou, "ui", None)
        if ui is not None and ui.displayMessage(
                messages.NO_USER_PICKED, buttons=messages.BUTTONS_OPEN_PREFERENCES,
                default_choice=0, close_choice=1,
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning) == 0:
            self.pane.ui.show_prefs(page="Library")    # where a library is picked with its user
        return ""

    def open_folder(self) -> None:
        """Open the Library Folder in the system's file browser."""
        if not self.pane.material_model:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_OPEN,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        hostos.open_path(self.pane.prefs.dir)

    def _start_save_timer(self) -> None:
        """This pane's save timer: a burst of changes is one save, written when it fires or at close."""
        if self._save_timer is not None:
            return
        timer = self._save_timer = QtCore.QTimer(self.pane)    # owned, so it is deleted with the pane ▸r/model-parent
        timer.setSingleShot(True)
        timer.setInterval(documents.SAVE_DELAY_MS)
        timer.timeout.connect(library_db.flush)
        schedule = timer.start
        library_db.set_scheduler(schedule)
        self.pane.destroyed.connect(functools.partial(_flush_saves_on_close, schedule))
        app = QtCore.QCoreApplication.instance()
        if app is not None and not getattr(app, "_amaze_flush_at_quit", False):
            app.aboutToQuit.connect(library_db.flush)
            app._amaze_flush_at_quit = True

    def _grid_proxy(self, proxy, model) -> tuple:
        """`proxy` set up over `model` the one way grid proxies are, and its selection model."""
        proxy.setSourceModel(model)
        proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        proxy.setDynamicSortFilter(False)    # the base class re-filters ▸r/proxy-invariant
        proxy.layoutChanged.connect(self.pane.grid_reordered)    # another pane may sort the model
        return proxy, QtCore.QItemSelectionModel(proxy, self.pane)

    def _sidebar_proxy(self, model):
        """A sidebar proxy over `model`: never sorted, as the stored order is the sidebar's."""
        proxy = category.CategoriesSidebarProxy(self.pane)
        proxy.setSourceModel(model)
        proxy.hide_empty = self.pane.prefs.hide_empty_categories
        return proxy

    def setup(self) -> None:
        """Build the models, this pane's proxies and selections, and the sections; show the first."""
        pane = self.pane
        self._start_save_timer()
        for attr, model in model_registry.models_for(pane.prefs).items():
            setattr(pane, attr, model)    # shared with every pane on this library; the proxies below are this pane's
        files_actions.connect(pane.file_files_model, pane.file_folders_model,
                              os_icon=pane.ui.os_file_icon)
        if pane.files.scene_watch is None:    # one callback per pane, however often setup runs
            pane.files.scene_watch = files_actions.watch_scene(pane.file_folders_model)
            pane.destroyed.connect(    # holds the callback, never the pane
                functools.partial(files_actions.unwatch_scene, pane.files.scene_watch))
        material_actions.connect(pane.material_model)
        self._note_models_library()

        pane.category_sorted_model = self._sidebar_proxy(pane.category_model)
        pane.material_sorted_model, pane.material_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(pane), pane.material_model)
        pane.file_sorted_model, pane.file_selection_model = self._grid_proxy(
            texture_library.TextureFilterProxyModel(pane), pane.file_files_model)
        pane.file_files_model.progress_changed.connect(
            pane._on_file_folder_progress)    # a bound method, never a lambda: the model outlives a closed pane tab
        pane.gradient_category_sorted_model = self._sidebar_proxy(pane.gradient_categories_model)
        pane.gradient_sorted_model, pane.gradient_selection_model = self._grid_proxy(
            gradient_library.GradientFilterProxyModel(pane), pane.gradient_model)
        pane.cop_category_sorted_model = self._sidebar_proxy(pane.cop_category_model)
        pane.cop_sorted_model, pane.cop_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(pane), pane.cop_model)
        pane.code_category_sorted_model = self._sidebar_proxy(pane.code_category_model)
        pane.code_sorted_model, pane.code_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(pane), pane.code_model)

        pane.matx_online_model = matx_library.MatxOnlineLibrary(    # the online MaterialX browser, with MaterialLibrary's role numbers
            preferences=pane.prefs
        )
        pane.matx_sorted_model, pane.matx_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(pane), pane.matx_online_model)
        pane.matx_source_model = matx_library.MatxSidebarModel(
            pane.matx_online_model
        )
        pane.matx_online_model.progress_changed.connect(    # preview downloads update the same bar as texture/geo thumbs
            pane._on_online_preview_progress
        )
        pane.online_mode = False
        pane.online_source = None
        pane.online_context = online_section.OnlineContext(pane)
        pane.sections = sections.build_sections(pane)    # one object per tab; shared handlers dispatch through active_section()
        pane.models_built.emit()    # the host's delegates exist before the first section binds them

        pane.current_section = next(    # the first enabled section
            (k for k, _ in pane.ALL_SECTIONS if k in pane.prefs.enabled_sections),
            "material",
        )
        pane.show_context(pane.sections[pane.current_section])    # the path a tab click takes
        pane.library_shown.emit()
        pane.online_changed.emit()    # the online models exist from here on
