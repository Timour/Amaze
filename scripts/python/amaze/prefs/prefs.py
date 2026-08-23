"""What a setting IS. Reading and WRITING the document is `persistence.py`'s, which `Prefs` inherits."""

import os
import json
import hou

import amaze
from amaze import branding
from amaze.core import database
from amaze.core import debug
from amaze.helpers import hostos
from amaze.prefs.persistence import (
    RENDERER_DEFAULTS,
    _INTRODUCED_SECTIONS,
    _Persistence,
    _decode_path,
    _default_sections,
)


TEST_LIB_SUBDIR = "lib"  # the library inside a test folder, named once because the dialog, the seeder and the overlay all have to agree. A `cache/` left in an older test folder is inert ▸ `cache_dir`
IMG_SUBDIR = "img/"  # the two folders a library cannot work without: `panel.ensure_library_dirs` and `seed_test_folder` each CREATE the pair, and `persistence.load()` still spells both defaults literally ▸p/library-creation-doors
ASSET_SUBDIR = "mat/"


def test_library_dir(folder: str) -> str:
    """The library inside a test folder, with the trailing separator the connectors concatenate onto. ▸r/atomic-writes"""
    if not folder:
        return ""
    return _normalised_dir(os.path.join(folder, TEST_LIB_SUBDIR))


def _normalised_dir(path: str) -> str:
    """Forward slashes and one trailing slash - the shape save() already forces on `directory`, so the overlay cannot hand out a differently-shaped path than the field it stands in for."""
    out = str(path).replace("\\", "/")
    if out and not out.endswith("/"):
        out += "/"
    return out


def write_fresh_index(path: str, document: dict) -> None:
    """Write a library index BORN at the current schema. Every creation door writes its index through here, so the two stamps cannot be half-applied by one of them. ▸p/library-creation-doors"""
    born = dict(document)
    born["version"] = database.SCHEMA_VERSION
    born["format"] = branding.LIBRARY_FORMAT
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(born, handle)


def seed_starter_index(lib_dir: str) -> None:
    """Seed `lib_dir` from the SHIPPED starter, stamped on the way in. Adds nothing if an index is already there. Raises OSError or ValueError if the starter itself cannot be read. ▸p/library-creation-doors"""
    index = os.path.join(lib_dir, "library.json")
    if os.path.exists(index):
        return
    with open(amaze.package_file("res", "def", "library.json"),
              encoding="utf-8") as handle:
        write_fresh_index(index, json.load(handle))


def seed_test_folder(folder: str) -> tuple:
    """Make `folder` usable as a test library - a WHOLE one, index and both asset folders. Returns (ok, what), and only ever adds what is missing. ▸p/library-creation-doors"""
    if not folder:
        return (False, "no folder")
    made = []
    try:
        path = os.path.join(folder, TEST_LIB_SUBDIR)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            made.append(TEST_LIB_SUBDIR + "/")
        for tail in (IMG_SUBDIR, ASSET_SUBDIR):
            folder_path = os.path.join(path, tail)
            if not os.path.isdir(folder_path):
                made.append(tail)
            os.makedirs(folder_path, exist_ok=True)
        index = os.path.join(folder, TEST_LIB_SUBDIR, "library.json")
        if not os.path.exists(index):
            write_fresh_index(index, {"categories": ["_All"], "tags": [],
                                      "assets": []})
            made.append("library.json")
    except OSError as exc:
        debug.event("prefs", "test folder could not be seeded",
                    folder=folder, error=str(exc))
        return (False, str(exc))
    return (True, ", ".join(made) if made else "already complete")


class Prefs(_Persistence):
    """Holds and loads the Preferences. A location is ONE RECORD in the library's `locations.json` and `locations.FIELDS` defines it; the settings.json keys are the copy, not the home. Asset favourites are NOT here - every section's star goes through `locations.is_favourite`/`set_favourite`, and `material_favorites` in settings.json is a migration source `locations.migrate_asset_favourites` reads and retires."""

    def __init__(self) -> None:
        """Every default a `save()` before a successful `load()` needs, so neither can AttributeError. ▸p/prefs-defaults"""
        self.path: str = hostos.config_root()  # where the OS keeps preferences, never under $AMAZE - that puts a user's library path inside the plugin folder, and inside a git tree for anyone who installed by cloning
        self._directory = ""
        self.data = {}
        self._ext = ".mat"
        self._img_ext = ".png"
        self._img_dir = IMG_SUBDIR
        self._asset_dir = ASSET_SUBDIR
        self._rendersize = 256
        self._rendersamples = 256
        self._render_on_import = 1
        for _attr, _default in RENDERER_DEFAULTS.items():  # THE SAME DEFAULTS load() APPLIES, from one table - this list was all False against load()'s True/False/True/True, only ONE of the four agreeing, and a machine with no settings.json kept the Falses and opened with every renderer switched off ▸p/prefs-defaults
            setattr(self, _attr, _default)
        self._show_categories = True
        self._section_filters: dict = {}  # the Filter menu's choice PER SECTION KEY, as the entry's LABEL - one shared key narrowed Nodes to nothing when Materials picked Redshift, and a label survives a section changing what its entries filter ON
        self._view_mode = "grid"
        self._thumbsize = 128  # grid (the legacy key); `_thumbsize_list` is the list view. Both match ClickSlider.DEFAULT_VALUE
        self._thumbsize_list = 128
        self._library_user = ""  # WHO this is - the ONE identity, keying everything stored per user AND signing versions. Blank = nobody picked yet; NEVER backfilled from the machine ▸p/identity-is-chosen
        self._file_folders: list[str] = []  # the File section's one folder/favourite/last quartet, and since 2026-08-12 the only one
        self._file_favorites: list[str] = []
        self._last_file_folder = ""
        self._file_show_unknown = True  # show files Amaze cannot thumbnail (the OS-icon rows); OFF restores the pre-merge view of recognised kinds only
        self._file_location_records: dict = {}  # THE LAST-KNOWN COPY of the library's location records, path -> record: written after every store write, never read back, and what the File section shows when the library is unreachable
        self._show_notes = False
        self._notes_panel_width = 0  # 0 = never dragged, so the 450px launch width applies
        self._sidebar_width = 0  # same contract, 220px design width - both side panes OWN their width and the grid is the splitter's only flexible pane
        self._path_style = "home"  # how Amaze WRITES paths: "home"/"job"/"hip" pin one variable, "absolute" writes the literal (the setter maps a stored "auto" to "home")
        self._geometry_shading_mode = "hiddenlineghost"  # flipbook ROP shadingmode token; paired with the black background below for the highest-contrast look out of the box
        self._geometry_bg = "black"  # "black"/"white" swap the flipbook's grey sky for a solid bgimage; "default" keeps the flipbook's own look
        self._icon_line_weight = "template"  # "template" (the design template's thin 10px stroke) or "feather" (the icon set's default) - a look, not a measurement, which is why it is a preference
        self._sidebar_counts = True  # entry counts on INDIVIDUAL categories/folders; "All" always shows its total regardless
        self._ram_cache_mb = 256  # past it, least-recently-viewed thumbnails drop from memory and reload from disk when scrolled back
        self._cache_dir = ""  # "" = this OS's own convention via hostos.cache_root()
        self._test_mode = False  # THE TEST LIBRARY OVERLAY, and an overlay never a write: `_directory` keeps the real path the whole time, because that is the only way back. It moves the LIBRARY only - the cache is keyed by file path, so moving it threw thousands of valid thumbnails away and protected nothing ▸ `cache_dir`
        self._test_dir = ""
        self._hide_empty_categories = True  # for Materials, "empty" respects the active renderer filter
        self._enabled_sections = _default_sections()
        self._sections_seen = {  # a fresh Prefs has every section, so their seen flags start recorded; load() recomputes from the active user's block
            "enabled_sections_seen_%s" % key: True
            for key in _INTRODUCED_SECTIONS}
        self._texture_parallel_conversions = 4  # how many iconvert conversions run at once (1-8)
        self._accent_color = "#5d7abd"  # size slider / progress bar; matches ClickSlider.LEFT_COLOR
        self._karma_rendersamples = 9  # Karma's own default, and separate from `rendersamples` which drives the Redshift ROP's UnifiedMaxSamples - the CPU engine needs far fewer
        self._scroll_speed = 0.75  # wheel factor for the grid/list, settled by live tuning and shown as a percent in Preferences
        self._debug_mode = False
        self._matx_parallel_downloads = 8
        self._matx_resolution = "2k"
        self._users_blocks: dict = {}  # uid -> the keys that are one user's on THIS machine

    def get_dir_from_user(self) -> bool:
        """Get Directory from User and write into prefs"""
        ui = getattr(hou, "ui", None)
        count = 0
        while count < 3:
            if not os.path.exists(self._directory) or count < 1:
                if ui is None:      # nobody to ask, so fall through to the branch that ACCEPTS a library already on disk
                    count += 1
                    continue
                if count > 0:   # only a RETRY speaks - the first picker follows the user's own gesture, and the set-up preamble it used to carry was a dialog in front of the dialog ▸p/dialogs-are-a-bill; its context is the title below now
                    ui.displayMessage("Invalid Path selected. Please try again")
                path = ui.selectFile(file_type=hou.fileType.Directory,
                                     title="Choose a folder for your Amaze library")
                if path == "":  # Canceled
                    return False
                self.dir = hou.expandString(path)  # through the SETTER, so meeting the picked library adopts its shared settings before the save below
            else:
                debug.event("session", "library set", dir=self._directory)
                self.save()
                return True
            count += 1
        return False

    @property
    def dir(self) -> str:
        """The library directory - the TEST one while Test Mode is on - carrying the trailing separator the connectors concatenate onto. ▸r/atomic-writes"""
        if getattr(self, "_test_mode", False) and getattr(  # getattr, because a Prefs built through __new__ is a SANCTIONED fixture shape and a property added later has to answer for those too
                self, "_test_dir", ""):
            return test_library_dir(self._test_dir)
        return self._directory

    @dir.setter
    def dir(self, val: str) -> None:
        self._directory = val  # the REAL path, always: writing the overlay through here would destroy the only route back, which is why the Preferences rows that set it are disabled while the switch is on
        self._adopt_shared()  # `dir` can be set long after load() - a fresh install picking the folder in a dialog - and without this the first save would push this machine's defaults over the library's answers

    @property
    def real_dir(self) -> str:
        """The configured library, ignoring the Test Mode overlay - for the few callers whose subject is the REAL library whatever the session points at, such as the disaster rehearsals."""
        return self._directory

    @property
    def test_mode(self) -> bool:
        """The LIBRARY points at the test folder instead; the cache does not move with it ▸ `cache_dir`."""
        return self._test_mode

    @test_mode.setter
    def test_mode(self, val: bool) -> None:
        self._test_mode = bool(val)

    @property
    def test_dir(self) -> str:
        """The folder holding `lib/`; "" = none chosen."""
        return self._test_dir

    @test_dir.setter
    def test_dir(self, val: str) -> None:
        self._test_dir = str(val or "")

    @property
    def rendersize(self) -> int:
        return self._rendersize

    @rendersize.setter
    def rendersize(self, val: int) -> None:
        self._rendersize = val

    @property
    def rendersamples(self) -> int:
        return self._rendersamples

    @rendersamples.setter
    def rendersamples(self, val: int) -> None:
        self._rendersamples = val

    @property
    def show_categories(self) -> bool:
        return self._show_categories

    @show_categories.setter
    def show_categories(self, val: bool) -> None:
        self._show_categories = val

    def section_filter(self, key: str, default: str = "") -> str:
        """The Filter menu entry this section was left on, by label. A PAIR OF METHODS, not a property over the dict: a property would hand callers something they could mutate without ever reaching save()."""
        return self._section_filters.get(str(key), default)

    def set_section_filter(self, key: str, label: str) -> None:
        self._section_filters[str(key)] = str(label or "")

    @property
    def view_mode(self) -> str:
        return self._view_mode

    @view_mode.setter
    def view_mode(self, val: str) -> None:
        self._view_mode = val if val in ("grid", "list") else "grid"

    @property
    def thumbsize(self) -> int:
        """Icon size for GRID view, kept under the legacy 'thumbsize' key."""
        return self._thumbsize

    @thumbsize.setter
    def thumbsize(self, val: int) -> None:
        self._thumbsize = val

    @property
    def thumbsize_list(self) -> int:
        """Icon size for LIST view - independent of the grid size."""
        return self._thumbsize_list

    @thumbsize_list.setter
    def thumbsize_list(self, val: int) -> None:
        self._thumbsize_list = val

    @property
    def render_on_import(self) -> int:
        return self._render_on_import

    @render_on_import.setter
    def render_on_import(self, val: int) -> None:
        self._render_on_import = val

    @property
    def img_dir(self) -> str:
        return self._img_dir

    @property
    def asset_dir(self) -> str:
        return self._asset_dir

    @property
    def img_ext(self) -> str:
        return self._img_ext

    @property
    def ext(self) -> str:
        return self._ext

    @property
    def renderer_matx_enabled(self) -> bool:
        return self._renderer_matx_enabled

    @renderer_matx_enabled.setter
    def renderer_matx_enabled(self, val: bool) -> None:
        self._renderer_matx_enabled = val

    @property
    def matx_resolution(self) -> str:
        """Preferred texture resolution for online MaterialX downloads - a FLOOR, not a requirement: lacking it the importer takes the next highest, else the highest below ▸ `matx_sources.pick_resolution`."""
        return self._matx_resolution

    @matx_resolution.setter
    def matx_resolution(self, val: str) -> None:
        self._matx_resolution = str(val or "2k")

    @property
    def renderer_redshift_enabled(self) -> bool:
        return self._renderer_redshift_enabled

    @renderer_redshift_enabled.setter
    def renderer_redshift_enabled(self, val: bool) -> None:
        self._renderer_redshift_enabled = val

    @property
    def renderer_octane_enabled(self) -> bool:
        return self._renderer_octane_enabled

    @renderer_octane_enabled.setter
    def renderer_octane_enabled(self, val: bool) -> None:
        self._renderer_octane_enabled = val


    @property
    def library_user(self) -> str:
        """WHICH user this machine is, for the current library: a UID, and a POINTER not a name - resolving it may MINT, which is `users.current(prefs)`'s job, not this file's. ▸p/identity-is-chosen"""
        return self._library_user

    @library_user.setter
    def library_user(self, value: str) -> None:
        value = str(value or "").strip()
        previous = getattr(self, "_library_user", "")
        self._library_user = value
        if value != previous:
            self._switch_user_state(previous, value)


    @property
    def file_folders(self) -> list[str]:
        """THE REGISTERED LOCATIONS - the library's answer, DERIVED not stored here; `_file_folders` is the last-known COPY, and `core/locations.py` says why a copy is never a second truth."""
        from amaze.core import locations
        return locations.registered_paths(self)

    @property
    def last_known_folders(self) -> list[str]:
        """The settings.json copy, verbatim. `locations` reads it for the sidebar's ORDER and as the fallback; nothing else should."""
        return self._file_folders

    @property
    def last_known_favourites(self) -> list[str]:
        return self._file_favorites

    @property
    def last_known_records(self) -> dict:
        return self._file_location_records

    def keep_last_known(self, records, order, favourites) -> None:
        """Refresh the settings.json copy from the library and persist. ONE writer, `core/locations.py` after a store write; a None means that store could not be READ, so its copy is left exactly as it was rather than blanked - losing the fallback is what the fallback exists to prevent."""
        if records is not None:
            self._file_location_records = {
                path: dict(value) for path, value in records.items()}
        if order is not None:
            self._file_folders = list(order)
        if favourites is not None:
            self._file_favorites = list(favourites)
        self.save()

    def hold_folder_order(self, order) -> None:
        """Stage a USER-AUTHORED sidebar order WITHOUT saving - the reorder gesture's in-flight state; `locations.move_registered` is the only caller and `commit_registered_order` persists it on release. Storage spelling, like everything in `_file_folders`."""
        self._file_folders = [str(p) for p in (order or [])]

    def add_file_folder(self, path: str) -> None:
        from amaze.core import locations
        locations.register(self, path)

    def remove_file_folder(self, path: str) -> None:
        from amaze.core import locations
        locations.unregister(self, path)

    def relocate_file_folder(self, old: str, new: str) -> bool:
        """Re-point one registered location, KEEPING ITS ROW - label, colour, recursion and Show All Files travel with it."""
        from amaze.core import locations
        if not old or not new or old == new:
            return False
        record = locations.record(self, old)
        if not record:
            return False
        at = (self._file_folders.index(old)
              if old in self._file_folders else len(self._file_folders))
        locations.relocate_record(self, old, new)
        if new in self._file_folders:
            self._file_folders.remove(new)
        self._file_folders.insert(min(at, len(self._file_folders)), new)
        self.save()
        return True

    def move_file_folder(self, path: str, row: int) -> bool:
        """Move one registered location to sidebar row `row` (0-based among the folders, the All row excluded) IN MEMORY - the gesture saves once on release, through the same locations-module door its siblings use."""
        from amaze.core import locations
        return locations.move_registered(self, path, row)

    @property
    def file_favorites(self) -> list[str]:
        """The user's File favourites as paths - the panel's prune sweep reads and removes through this trio when a favourited path is gone for good."""
        from amaze.core import locations
        return locations.favourite_paths(self)

    def add_file_favorite(self, path: str) -> None:
        from amaze.core import locations
        locations.set_favourite(self, path, True)  # remove's symmetric half - the panel favourites through the grid today, and a one-sided pair invites drift

    def remove_file_favorite(self, path: str) -> None:
        from amaze.core import locations
        locations.set_favourite(self, path, False)

    @property
    def last_file_folder(self) -> str:
        return self._last_file_folder

    @last_file_folder.setter
    def last_file_folder(self, val: str) -> None:
        self._last_file_folder = str(val or "")

    @property
    def file_show_unknown(self) -> bool:
        return self._file_show_unknown

    @file_show_unknown.setter
    def file_show_unknown(self, val: bool) -> None:
        self._file_show_unknown = bool(val)

    @property
    def file_recursive_folders(self) -> list[str]:
        return self._field_paths("recursive")

    def set_file_folder_recursive(self, path: str, on: bool) -> None:
        self._set_location_field(path, "recursive", bool(on) or None)

    @property
    def file_folder_names(self) -> dict:
        return self._field_table("name")

    def set_file_folder_name(self, path: str, name: str) -> None:
        """Custom display name for a location; empty clears it back to the default, the path itself."""
        self._set_location_field(path, "name", str(name or "").strip())

    @property
    def file_folder_colors(self) -> dict:
        return self._field_table("color")

    @property
    def file_folder_show_all(self) -> dict:
        return self._field_table("show_all")

    def set_file_folder_show_all(self, path: str, value) -> None:
        """The per-location Show All Files checkbox; None clears the override so the location follows the global preference."""
        self._set_location_field(
            path, "show_all", None if value is None else bool(value))

    def set_file_folder_color(self, path: str, color: str) -> None:
        """Colour one location, or clear it with an empty colour - the File section's Set Color / Clear Color."""
        self._set_location_field(path, "color", str(color or "").strip())


    def _field_table(self, field: str) -> dict:
        from amaze.core import locations
        table = {}
        for path in locations.paths(self):
            record = locations.record(self, path)
            if field in record:
                table[path] = record[field]
        return table

    def _field_paths(self, field: str) -> list[str]:
        from amaze.core import locations
        return [path for path in locations.registered_paths(self)
                if locations.record(self, path).get(field)]

    def _set_location_field(self, path: str, field: str, value) -> None:
        from amaze.core import locations
        if not path:
            return
        locations.set_field(self, path, field, value)

    @property
    def show_notes(self) -> bool:
        return self._show_notes

    @show_notes.setter
    def show_notes(self, val: bool) -> None:
        self._show_notes = bool(val)

    @property
    def notes_panel_width(self) -> int:
        return self._notes_panel_width

    @notes_panel_width.setter
    def notes_panel_width(self, val: int) -> None:
        try:
            self._notes_panel_width = max(0, int(val))
        except (TypeError, ValueError):
            self._notes_panel_width = 0

    @property
    def sidebar_width(self) -> int:
        return self._sidebar_width

    @sidebar_width.setter
    def sidebar_width(self, val: int) -> None:
        try:
            self._sidebar_width = max(0, int(val))
        except (TypeError, ValueError):
            self._sidebar_width = 0

    @property
    def path_style(self) -> str:
        return self._path_style

    @path_style.setter
    def path_style(self, val: str) -> None:
        val = str(val or "home")
        self._path_style = val if val in (
            "absolute", "hip", "job", "home") else "home"

    @property
    def geometry_shading_mode(self) -> str:
        return self._geometry_shading_mode

    @geometry_shading_mode.setter
    def geometry_shading_mode(self, val: str) -> None:
        self._geometry_shading_mode = str(val or "hiddenlineghost")

    @property
    def geometry_bg(self) -> str:
        return self._geometry_bg

    @geometry_bg.setter
    def geometry_bg(self, val: str) -> None:
        self._geometry_bg = str(val or "black")

    @property
    def icon_line_weight(self) -> str:
        """"template" (thin) or "feather" (the icon set's own weight)."""
        return self._icon_line_weight

    @icon_line_weight.setter
    def icon_line_weight(self, val: str) -> None:
        val = str(val or "template")
        self._icon_line_weight = val if val in ("template", "feather") \
            else "template"

    @property
    def sidebar_counts(self) -> bool:
        return self._sidebar_counts

    @sidebar_counts.setter
    def sidebar_counts(self, val: bool) -> None:
        self._sidebar_counts = bool(val)

    @property
    def ram_cache_mb(self) -> int:
        return self._ram_cache_mb

    @ram_cache_mb.setter
    def ram_cache_mb(self, val: int) -> None:
        self._ram_cache_mb = min(4096, max(64, int(val)))

    @property
    def cache_dir(self) -> str:
        """Custom thumbnail-cache root; "" = the per-OS default. TEST MODE DOES NOT MOVE IT - thumbnails are keyed by file path and say nothing about which library is open, so a switch that moved them threw away thousands of valid images (measured 2026-08-08: 2496 texture and 503 geometry, against a test cache holding 106 and none)."""
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, val: str) -> None:
        self._cache_dir = str(val or "")

    @property
    def hide_empty_categories(self) -> bool:
        return self._hide_empty_categories

    @hide_empty_categories.setter
    def hide_empty_categories(self, val: bool) -> None:
        self._hide_empty_categories = bool(val)

    @property
    def enabled_sections(self) -> list:
        return self._enabled_sections

    @enabled_sections.setter
    def enabled_sections(self, val) -> None:
        # Never leave the panel with no tabs - fall back to Materials.
        val = [str(k) for k in val] if val else []
        self._enabled_sections = val or ["material"]

    @property
    def texture_parallel_conversions(self) -> int:
        return self._texture_parallel_conversions

    @texture_parallel_conversions.setter
    def texture_parallel_conversions(self, val: int) -> None:
        self._texture_parallel_conversions = max(1, min(8, int(val)))

    @property
    def karma_rendersamples(self) -> int:
        return self._karma_rendersamples

    @karma_rendersamples.setter
    def karma_rendersamples(self, val: int) -> None:
        self._karma_rendersamples = max(1, int(val))

    @property
    def scroll_speed(self) -> float:
        return self._scroll_speed

    @scroll_speed.setter
    def scroll_speed(self, val: float) -> None:
        self._scroll_speed = max(0.1, min(3.0, float(val)))

    @property
    def debug_mode(self) -> bool:
        """Write a structured session log for deep analysis. OFF by default - a diagnostic tool, not a normal running mode."""
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, val: bool) -> None:
        self._debug_mode = bool(val)

    @property
    def matx_parallel_downloads(self) -> int:
        """Concurrent preview downloads in the online browser - latency-bound not bandwidth-bound, so concurrency scales almost linearly (measured 32 PolyHaven previews: 1 -> 220ms each, 8 -> 42ms, 16 -> 18ms). Capped at 16 to stay a polite client of free public APIs."""
        return self._matx_parallel_downloads

    @matx_parallel_downloads.setter
    def matx_parallel_downloads(self, val: int) -> None:
        self._matx_parallel_downloads = max(1, min(16, int(val)))

    @property
    def accent_color(self) -> str:
        return self._accent_color

    @accent_color.setter
    def accent_color(self, val: str) -> None:
        self._accent_color = val if val else "#5d7abd"

