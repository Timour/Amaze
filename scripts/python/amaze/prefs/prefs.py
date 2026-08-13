"""
Holds the Preferences for the Matlib.

WHAT IS LEFT HERE, and why it is not split further: this file is one
responsibility now - what a setting IS. Its bulk is 64 property pairs
plus the accessors for the things a preference can be ABOUT (the
library pointer, registered file locations, favourites, per-section
filters), and each pair is four lines that read as one. Splitting an
alphabet of settings across modules divides a list, not a
responsibility, and every call site would then have to know which half
a name lives in.

Reading and WRITING the document is a different job and lives in
`persistence.py`, which `Prefs` inherits (ROADMAP line 9, 2026-08-09).
"""

import os
import json
import hou

from amaze.core import debug
from amaze.helpers import hostos
from amaze.prefs.persistence import (
    RENDERER_DEFAULTS,
    _INTRODUCED_SECTIONS,
    _Persistence,
    _decode_path,
    _default_sections,
)


#: The library inside a test folder. Named once, because the dialog,
#: the seeder and the overlay all have to agree.
#:
#: There is no cache subfolder any more: Test Mode moves the LIBRARY
#: only. The thumbnail caches are keyed by file path on disk, so
#: moving them regenerated thousands of valid images per switch and
#: protected nothing (`cache_dir` says the measurement). A `cache/`
#: left in an existing test folder is inert.
TEST_LIB_SUBDIR = "lib"

#: `DEFAULT_LIBRARY_USER` LIVED HERE AND IS GONE (2026-08-12). It was a
#: fixed name every install started at, so two untouched machines would
#: agree; the identity is a UID now, and a library with no users mints
#: one from `users.PLACEHOLDER_NAMES` while a library that HAS users
#: asks which one this machine is. The prompt does the job the fixed
#: default was doing, and does it better - two real people are told
#: apart on sight, where two `Artist`s could not be.
#:
#: Naming a user is `core/users.py`'s, not this file's. What stays here
#: is the ban it inherits: `hostos.machine_name()`, `platform.node`,
#: `getpass` and `$USER` may never reach an identity, in either module.


def test_library_dir(folder: str) -> str:
    """The library inside a test folder, with the trailing separator
    the connectors need (they build `self._path + self._filename`)."""
    if not folder:
        return ""
    return _normalised_dir(os.path.join(folder, TEST_LIB_SUBDIR))


def _normalised_dir(path: str) -> str:
    """Forward slashes and one trailing slash - the shape save()
    already forces on `directory`, so the overlay cannot hand out a
    differently-shaped path than the field it stands in for."""
    out = str(path).replace("\\", "/")
    if out and not out.endswith("/"):
        out += "/"
    return out


def seed_test_folder(folder: str) -> tuple:
    """Make `folder` usable as a test library. Returns (ok, what).

    A library directory with no `library.json` does not load - absence
    of the PRIMARY database is a real error the caller must surface,
    not something the connector papers over (core/database.py). So
    switching Test Mode on at a fresh folder has to seed one, or the
    switch would hand back a traceback.

    The index written here is the same document the connector writes
    for an absent SIBLING database, so a seeded library and a
    self-created one are the same thing. Existing files are never
    touched: this only ever adds what is missing.
    """
    if not folder:
        return (False, "no folder")
    made = []
    try:
        path = os.path.join(folder, TEST_LIB_SUBDIR)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            made.append(TEST_LIB_SUBDIR + "/")
        index = os.path.join(folder, TEST_LIB_SUBDIR, "library.json")
        if not os.path.exists(index):
            with open(index, "w", encoding="utf-8") as handle:
                json.dump({"categories": ["_All"], "tags": [],
                           "assets": []}, handle)
            made.append("library.json")
    except OSError as exc:
        debug.event("prefs", "test folder could not be seeded",
                    folder=folder, error=str(exc))
        return (False, str(exc))
    return (True, ", ".join(made) if made else "already complete")


# The four per-location surfaces used to be listed here, as the one
# address for "everything this location keeps" - they were open-coded
# per entry, and the two added later (`file_folder_colors` 2026-07-31,
# `file_folder_show_all` 2026-08-01) were never joined to the Locate
# Folder hook or to removal.
#
# They are not surfaces any more. A location is ONE RECORD in the
# library's own `locations.json`, and the list that defines it is
# `locations.FIELDS` - which also carries `registered`, the fact that
# had no surface of its own and so could not be seen at all by anything
# walking the four. The settings.json keys are still written, as the
# copy; they are just no longer where a location lives.


class Prefs(_Persistence):
    """
    Holds and loads the Preferences for the Matlib
    """

    def __init__(self) -> None:
        # Preferences live where the OS keeps preferences, NOT in the
        # install: settings under $AMAZE put a user's library path and
        # favorites inside the plugin folder - and inside a git working
        # tree for anyone who installed by cloning, where a pull could
        # conflict with them and a checkout could blank them.
        self.path: str = hostos.config_root()
        self._directory = ""
        self.data = {}
        # Storage-format constants and render basics, initialized here
        # (not only in load()) so save() before a successful load()
        # cannot AttributeError, and so a settings.json missing any of
        # these keys still loads via the .get() defaults below.
        self._ext = ".mat"
        self._img_ext = ".png"
        self._img_dir = "img/"
        self._asset_dir = "mat/"
        self._rendersize = 256
        self._rendersamples = 256
        self._render_on_import = 1
        # THE SAME DEFAULTS load() APPLIES. These were all False here
        # and True/False/True/True there, and only Mantra agreed - so
        # on a machine with NO settings.json, load() returns at its
        # FileNotFoundError branch before reaching those .get() calls
        # and the object keeps four Falses, which refresh_data() then
        # writes out on the first save. A new machine opened with
        # Karma, Redshift and Octane all switched off: the Materials
        # Filter menu offered only "All" over a library full of Karma
        # and Redshift, and closing Preferences made it permanent.
        for _attr, _default in RENDERER_DEFAULTS.items():
            setattr(self, _attr, _default)
        # Panel view state: category list shown by default
        self._show_categories = True
        # The Filter menu's remembered choice, per section key, as the
        # entry's LABEL. Every section has its own filter now (the
        # renderers were only the first), and one shared key would have
        # meant picking Redshift in Materials and finding Nodes
        # narrowed to nothing. Labels rather than values because a
        # label is what the menu can look itself up by, and it survives
        # a section changing what its entries filter ON.
        self._section_filters: dict = {}
        self._view_mode = "grid"
        # Per-view-mode icon sizes: thumbsize = grid (legacy key),
        # thumbsize_list = list. Both match ClickSlider.DEFAULT_VALUE.
        self._thumbsize = 128
        self._thumbsize_list = 128
        # WHO this is - the ONE identity. It keys everything stored per
        # user in the library AND it signs versions.
        #
        # IT USED TO BE TWO FIELDS AND COULD NOT STAY TWO. `version_author`
        # needed the name to DIFFER per machine (so two machines never
        # mint one version filename); keying a user's things across their
        # machines needs it to MATCH. One preference cannot do both, and
        # the shipped default actively produced the wrong answer for the
        # second use (ROADMAP line 21). `version_author` is retired and
        # its value ADOPTED, so every `<name>-<n>` stem already on disk
        # still matches its writer.
        #
        # NEVER backfilled from the machine - hostos.machine_name(),
        # platform.node, getpass and $USER are all banned from this path:
        # an auto-harvested name puts a real person's identity into a
        # library that may be shared, without them choosing it. Blank
        # means nobody has been picked on this machine yet, which
        # `users.current(prefs)` answers - by minting when the library
        # has nobody, and by asking when it already has people.
        self._library_user = ""
        # The File section (the 2026-07-31 merge of Images, Geometry
        # and HIP): one folder/favorite/last/subfolders quartet, and
        # since 2026-08-12 the only one. The three per-section quartets
        # and their one-time union were swept - they existed so an older
        # build on this machine could still read them after a rollback,
        # which pre-1.0 is not owed.
        self._file_folders: list[str] = []
        self._file_favorites: list[str] = []
        self._last_file_folder = ""
        self._file_include_subfolders = False
        # Show files Amaze cannot thumbnail (the OS-icon rows) in the
        # File section. ON is the merge's behaviour - a folder shows
        # what is in it; OFF restores the pre-merge view where only
        # recognised kinds (image/geometry/hip) appear.
        self._file_show_unknown = True
        # Per-LOCATION recursion: the paths whose Include Subfolders is
        # on. Replaces the short-lived global file_include_subfolders
        # (still written as the OR of this list for one build of
        # cross-machine grace).
        self._file_recursive_folders: list[str] = []
        # Custom display names per location, path -> name. Empty = the
        # default, which is the path itself (Houdini-collapsed).
        self._file_folder_names: dict = {}
        # Location colours, path -> hex. The File section's answer to
        # category colours: same sidebar bar, same tile band, stored
        # here rather than in a database because a location is a
        # pointer this machine holds, not library content.
        self._file_folder_colors: dict = {}
        # Per-location Show All Files override (2026-08-01): absent =
        # follow the global file_show_unknown preference.
        self._file_folder_show_all: dict = {}
        # THE LAST-KNOWN COPY of the library's location records, path ->
        # record. Written from `locations.json` after every store write,
        # never read back into it. It is what the File section shows
        # when the library is unmounted, not yet synced, or unreadable -
        # the moment a browser is most wanted and least able to reach
        # its own truth. The six keys above are the same copy in the
        # shape an older build reads after a rollback HERE. Not the
        # other Mac - settings.json does not travel (INSTALL.md).
        self._file_location_records: dict = {}
        # The Notes panel's visibility, persisted so the notebook a
        # user works in stays open across sessions.
        self._show_notes = False
        # The Notes panel's dragged width, remembered across sessions
        # (0 = never dragged - the 450px launch width applies).
        self._notes_panel_width = 0
        # The category sidebar's dragged width, same contract (0 =
        # never dragged - the 220px design width applies). Both side
        # panes OWN their width; the grid is the splitter's only
        # flexible pane.
        self._sidebar_width = 0
        # How Amaze WRITES paths (Copy Path, location labels):
        # "home"/"job"/"hip" pin one variable, "absolute" writes the
        # literal path. (The one-day "auto" option was removed
        # 2026-08-01; the setter maps a stored "auto" to "home".)
        self._path_style = "home"
        # v2: geometry thumbnail shading mode (flipbook ROP shadingmode
        # menu token). Default = Hidden Line Ghost, with a black
        # background below - the highest-contrast out-of-the-box look.
        self._geometry_shading_mode = "hiddenlineghost"
        # v2: geometry thumbnail background - "black"/"white" swap the
        # flipbook's grey sky for a solid bgimage (for contrast);
        # "default" keeps the flipbook's own look. Black is the
        # default, paired with the hidden-line-ghost shading above.
        self._geometry_bg = "black"
        #: Tile-icon line weight: "template" (the design template's thin
        #: 10px stroke) or "feather" (the icon set's own default). A
        #: look, not a measurement - which is why it is a preference.
        self._icon_line_weight = "template"
        # v2: show entry counts on INDIVIDUAL sidebar categories/folders
        # ("All" always shows its total regardless).
        self._sidebar_counts = True
        # v2: RAM budget (MB) for the shared thumbnail image cache -
        # past it, least-recently-viewed thumbnails drop from memory
        # and reload from disk when scrolled back into view.
        self._ram_cache_mb = 256
        # v2: custom thumbnail-cache location ("" = this OS's own
        # convention via hostos.cache_root()). Stored portable like
        # every other path pref.
        self._cache_dir = ""
        # THE TEST LIBRARY OVERLAY. One switch and one folder: on, and
        # the library reads <folder>/lib/ and the cache <folder>/cache/.
        # An OVERLAY, never a write: _directory and _cache_dir keep the
        # real paths untouched the whole time it is on, because the only
        # way back is for them to still be there.
        #
        # Deliberately NOT tied to Debug Mode. Verbose logging exists to
        # diagnose the REAL library, so a rider that swapped the library
        # out would remove the one thing it is for.
        self._test_mode = False
        self._test_dir = ""
        # v2: hide sidebar categories with zero visible assets (for
        # Materials, "visible" respects the active renderer filter).
        # OFF = always show every category, the pre-hiding behavior.
        self._hide_empty_categories = True
        # v2: which section tabs are shown (order fixed elsewhere) - so
        # a user who only wants Materials + Code can hide the rest.
        self._enabled_sections = _default_sections()
        # A fresh Prefs has every section, introduced ones included,
        # so their seen flags start recorded - load() recomputes this
        # from the active user's block.
        self._sections_seen = {
            "enabled_sections_seen_%s" % key: True
            for key in _INTRODUCED_SECTIONS}
        # v2: favorited CURATED gradient combinations, as "<set>:<id>"
        # keys (e.g. "wada:132", "klee:7"). User gradients store their
        # favorite flag inline in gradients.json instead - they have no
        # stable id to key on here.
        # v2: how many iconvert conversions run at once (1-8, default 4)
        self._texture_parallel_conversions = 4
        # "texture_force_iconvert" lived here until 2026-08-03. The
        # KEY is deliberately not stripped from an existing
        # settings.json - load() keeps every key it read (self.data =
        # dict(data)) and refresh_data only overwrites the ones this
        # build owns, so an older machine reading the same file still
        # finds its value. Nothing may strip a stored key.
        # v2: accent color for the size slider / progress bar, "#rrggbb".
        # Default matches ClickSlider.LEFT_COLOR.
        self._accent_color = "#5d7abd"
        # v2: Karma thumbnail samples, separate from rendersamples (which
        # is the Redshift thumbnail dial - wired into the Redshift ROP's
        # UnifiedMaxSamples). Karma renders thumbnails on the CPU engine
        # and needs far fewer; 9 is Karma's own default.
        self._karma_rendersamples = 9
        # v2: wheel scroll speed factor for the thumbnail grid/list
        # (DragDropListView applies trackpad pixel deltas scaled by
        # this). 0.75 is the default settled on after live tuning
        # (1.0 scrolled roughly twice as fast as it should); shown as
        # a percent in Preferences.
        self._scroll_speed = 0.75
        self._debug_mode = False
        self._matx_parallel_downloads = 8
        # Online MaterialX browser: preferred download resolution.
        self._matx_resolution = "2k"
        # THE PER-USER DIMENSION (ROADMAP line 22): uid -> the block of
        # keys that are one user's on THIS machine. Carried whole and
        # empty until that line's flip commits move keys into it.
        self._users_blocks: dict = {}

    def get_dir_from_user(self) -> bool:
        """Get Directory from User and write into prefs"""
        count = 0
        while count < 3:
            if not os.path.exists(self._directory) or count < 1:
                if not os.path.exists(self._directory) and count < 1:
                    hou.ui.displayMessage("It looks like your library is not set up yet. Please choose a directory to store the library data")  # type: ignore
                elif count > 0:
                    hou.ui.displayMessage("Invalid Path selected. Please try again")
                path = hou.ui.selectFile(file_type=hou.fileType.Directory)
                if path == "":  # Canceled
                    return False
                # Through the setter, so meeting the picked library
                # adopts its shared settings before the save below.
                self.dir = hou.expandString(path)
            else:
                debug.event("session", "library set", dir=self._directory)
                self.save()
                return True
            count += 1
        return False

    @property
    def dir(self) -> str:
        """The library directory - the TEST one while Test Mode is on.

        A property, so the overlay is invisible to every caller: the
        models, the sweeps and the dialogs all keep asking one question
        and stop needing to know which world they are in.

        Trailing separator, like `_directory` carries: the connectors
        build a path as `self._path + self._filename`.

        getattr, because a Prefs built through `__new__` is a
        SANCTIONED fixture shape - a real one under hython resolves
        $AMAZE to the live install, which is how a test overwrote real
        settings once, so several fixtures borrow the accessors
        without the constructor. A property added later has to answer
        for those too.
        """
        if getattr(self, "_test_mode", False) and getattr(
                self, "_test_dir", ""):
            return test_library_dir(self._test_dir)
        return self._directory

    @dir.setter
    def dir(self, val: str) -> None:
        # The REAL path, always. Writing the overlay through here would
        # destroy the only route back to the real library, so the
        # Preferences rows that set it are disabled while the switch is
        # on and this stays the real field.
        self._directory = val
        # Meeting a library adopts its shared settings - `dir` can be
        # set long after load() (a fresh install picking the folder in
        # a dialog), and without this the first save would push this
        # machine's defaults over the library's answers.
        self._adopt_shared()

    @property
    def real_dir(self) -> str:
        """The configured library, ignoring the Test Mode overlay.

        For the few callers whose subject is the REAL library whatever
        the session is pointed at - the disaster rehearsals, which
        recover the owner's own snapshots and mean nothing against a
        throwaway.
        """
        return self._directory

    @property
    def test_mode(self) -> bool:
        """Library and cache point at the test folder instead."""
        return self._test_mode

    @test_mode.setter
    def test_mode(self, val: bool) -> None:
        self._test_mode = bool(val)

    @property
    def test_dir(self) -> str:
        """The folder holding `lib/` and `cache/`; "" = none chosen."""
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
        """The Filter menu entry this section was left on, by label.

        A pair of methods rather than a property over the whole dict:
        the dict is the storage, not the interface, and a property
        would hand callers something they could mutate without ever
        reaching save()."""
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
        """Icon size for GRID view (kept under the legacy 'thumbsize'
        key for backward compatibility)."""
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
        """Preferred texture resolution for online MaterialX downloads.
        A FLOOR, not a hard requirement: if a material lacks it, the
        importer takes the next highest, else the highest below (see
        matx_sources.pick_resolution)."""
        return self._matx_resolution

    @matx_resolution.setter
    def matx_resolution(self, val: str) -> None:
        self._matx_resolution = str(val or "2k")

    @property
    def renderer_mantra_enabled(self) -> bool:
        return self._renderer_mantra_enabled

    @renderer_mantra_enabled.setter
    def renderer_mantra_enabled(self, val: bool) -> None:
        self._renderer_mantra_enabled = val

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

    # -- registered locations and their favourites -------------------------
    #
    # THE MUTATORS ARE THE FILE FAMILY'S ONLY. There were four families
    # - texture, geometry, hip, file - of add/remove for folders and for
    # favourites, sixteen methods that differed in one attribute name.
    # The 2026-07-31 merge left `FileFolders` as the only
    # `FolderListModel` subclass, so twelve of them lost their last
    # caller and were deleted 2026-08-05.
    #
    # THE KEYS AND THE READ PROPERTIES ARE GONE (2026-08-12). They were
    # kept so an older build could still read them, which pre-1.0 is not
    # owed - and settings.json is per-machine, so there was no second
    # reader to serve in the first place. `file_folders` and
    # `file_favorites` are the whole surface now.

    @property
    def library_user(self) -> str:
        """WHICH user this machine is, for the current library: a UID.

        A POINTER, NOT A NAME. The name lives on the user's record in
        the library, so a rename relinks one label and moves nothing
        that is tagged. Blank means nobody has been picked here yet.

        THIS FILE CANNOT RESOLVE IT, and that is the split. Answering
        "who am I" may require MINTING a user into the library, which is
        `core/users.py`'s job - `users.current(prefs)`, which also
        answers None when the caller must ask rather than guess. Prefs
        holds the pointer and knows nothing about who it points at, the
        same way it holds `directory` without knowing what is in it.
        """
        return self._library_user

    @library_user.setter
    def library_user(self, value: str) -> None:
        value = str(value or "").strip()
        previous = getattr(self, "_library_user", "")
        self._library_user = value
        # A real change of WHO swaps whose view state the attributes
        # describe - snapshot the old user's, apply the new user's.
        # load() writes the field directly and reads the block itself,
        # so this fires only for the picker, the mint and the tests.
        if value != previous:
            self._switch_user_state(previous, value)

    # Material/Node/Code favourites left this class on 2026-08-13: every
    # section's star goes through `locations.is_favourite` /
    # `set_favourite` into the library's favourites store, keyed by
    # asset id and tagged with the owner. `material_favorites` in
    # settings.json is a migration source only, read and retired by
    # `locations.migrate_asset_favourites`.

    @property
    def file_folders(self) -> list[str]:
        """THE REGISTERED LOCATIONS - the library's answer.

        Derived since 2026-08-05, not stored here. `_file_folders` is
        the last-known COPY: what `save` writes, what `load` reads, and
        what shows when the library cannot be reached. See
        `core/locations.py` for why the copy is never a second truth.
        """
        from amaze.core import locations
        return locations.registered_paths(self)

    @property
    def last_known_folders(self) -> list[str]:
        """The settings.json copy, verbatim. `locations` reads this for
        the sidebar's ORDER and as the fallback; nothing else should."""
        return self._file_folders

    @property
    def last_known_favourites(self) -> list[str]:
        return self._file_favorites

    @property
    def last_known_records(self) -> dict:
        return self._file_location_records

    def keep_last_known(self, records, order, favourites) -> None:
        """Refresh the settings.json copy from the library, and persist.

        ONE writer, called only by `core/locations.py` after a store
        write. A None means that store could not be read, so its copy is
        left exactly as it was rather than being blanked - losing the
        fallback is the one outcome the fallback exists to prevent.
        """
        if records is not None:
            self._file_location_records = {
                path: dict(value) for path, value in records.items()}
        if order is not None:
            self._file_folders = list(order)
        if favourites is not None:
            self._file_favorites = list(favourites)
        self.save()

    def add_file_folder(self, path: str) -> None:
        from amaze.core import locations
        locations.register(self, path)

    def remove_file_folder(self, path: str) -> None:
        from amaze.core import locations
        locations.unregister(self, path)

    def relocate_file_folder(self, old: str, new: str) -> bool:
        """Re-point one registered location, KEEPING ITS ROW.

        Not remove-then-add: that would send a relocated folder to the
        bottom of the sidebar, and location order is registration order
        (there is no reorder gesture, so the order is not something the
        user authored and must not move on its own). The record travels
        whole, so the label, colour, recursion and Show All Files
        override arrive with it.
        """
        from amaze.core import locations
        if not old or not new or old == new:
            return False
        record = locations.record(self, old)
        if not record:
            return False
        at = (self._file_folders.index(old)
              if old in self._file_folders else len(self._file_folders))
        # ONE WRITE, not remove-then-add. Those were two independent
        # trips to disk, and a denial between them - one transient
        # outage of a synced library - deregistered the location and
        # took its record with it: colour, name, recursion and Show All
        # Files gone, the folder just missing. `relocate_record` is the
        # engine's `rekey`, which lands whole or not at all.
        locations.relocate_record(self, old, new)
        # The copy carries the ORDER, and the store cannot: put the new
        # path back in the row the old one held rather than wherever a
        # sorted key landed.
        if new in self._file_folders:
            self._file_folders.remove(new)
        self._file_folders.insert(min(at, len(self._file_folders)), new)
        self.save()
        return True

    @property
    def file_favorites(self) -> list[str]:
        from amaze.core import locations
        return locations.favourite_paths(self)

    def add_file_favorite(self, path: str) -> None:
        from amaze.core import locations
        locations.set_favourite(self, path, True)

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
    def file_include_subfolders(self) -> bool:
        return self._file_include_subfolders

    @file_include_subfolders.setter
    def file_include_subfolders(self, val: bool) -> None:
        self._file_include_subfolders = bool(val)

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
        """Custom display name for a location; empty clears it back
        to the default (the path itself)."""
        self._set_location_field(path, "name", str(name or "").strip())

    @property
    def file_folder_colors(self) -> dict:
        return self._field_table("color")

    @property
    def file_folder_show_all(self) -> dict:
        return self._field_table("show_all")

    def set_file_folder_show_all(self, path: str, value) -> None:
        """The per-location Show All Files checkbox; None clears the
        override so the location follows the global preference."""
        self._set_location_field(
            path, "show_all", None if value is None else bool(value))

    def set_file_folder_color(self, path: str, color: str) -> None:
        """Colour one location, or clear it with an empty colour -
        the File section's Set Color / Clear Color."""
        self._set_location_field(path, "color", str(color or "").strip())

    # THE FOUR DECORATIONS ARE ONE RECORD NOW, and these three helpers
    # are all that is left of the four parallel tables. Kept as the same
    # dict-and-list shapes their readers have always seen, so moving the
    # storage did not become a rewrite of every caller: `file_folders`
    # and friends appear 104 times across six files, and almost none of
    # them changed.

    def _load_location_copy(self, data: dict) -> None:
        """Rebuild the last-known records from settings.json.

        Prefers `file_location_records`, the copy this build writes.
        Falls back to composing one out of the six old keys, which is
        what a settings file written before 2026-08-05 holds - this
        machine's own, since settings.json does not travel between the
        two Macs (INSTALL.md). That fallback is not a migration: it is
        how the File section keeps working before a library has ever
        been reached.
        """
        stored = data.get("file_location_records", None)
        if isinstance(stored, dict):
            records = {}
            for key, value in stored.items():
                if isinstance(key, str) and isinstance(value, dict):
                    records[_decode_path(key)] = dict(value)
            if records:
                self._file_location_records = records
                return
        # From the ATTRIBUTES, not from `data`: by the time this runs,
        # load() has already merged the three pre-merge sections'
        # folder keys (texture/geometry/hip) into `_file_folders`, and
        # a pre-merge file has no `file_folders` key at all - composing
        # from the raw document came back empty and emptied the sidebar
        # (caught by MigrationTest the day this was tried). The MERGE
        # path composes from the raw document instead, because a peer
        # FILE is complete by definition - see
        # _compose_location_records.
        composed: dict = {}
        for path in self._file_folders:
            composed.setdefault(path, {})["registered"] = True
        for table, field in ((self._file_folder_names, "name"),
                             (self._file_folder_colors, "color"),
                             (self._file_folder_show_all, "show_all")):
            for path, value in table.items():
                composed.setdefault(path, {})[field] = value
        for path in self._file_recursive_folders:
            composed.setdefault(path, {})["recursive"] = True
        self._file_location_records = composed

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
        # "auto" (removed 2026-08-01) intentionally absent: a machine
        # that stored it lands on the default rather than a dead token.
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
        """Custom thumbnail-cache root; "" = the per-OS default.

        TEST MODE DOES NOT MOVE THIS. The File section's thumbnails are
        keyed by file path on disk and say nothing about which library
        is open, so moving the cache threw away thousands of valid
        images on every switch and regenerated them (measured
        2026-08-08: 2496 texture and 503 geometry thumbnails against a
        test cache holding 106 and none). There is nothing to protect
        the real cache from either - a test session only ever adds
        thumbnails that are correct and reusable.
        """
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
        """Write a structured session log for deep analysis. OFF by
        default - it is a diagnostic tool, not a normal running mode."""
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, val: bool) -> None:
        self._debug_mode = bool(val)

    @property
    def matx_parallel_downloads(self) -> int:
        """Concurrent preview downloads in the online browser.

        These are latency-bound, not bandwidth-bound (a 40KB thumbnail
        takes ~470ms from GPUOpen), so concurrency scales almost
        linearly: measured over 32 PolyHaven previews, 1 -> 220ms each,
        8 -> 42ms, 16 -> 18ms. Capped at 16 to stay a polite client of
        free public APIs."""
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

