"""
Holds and loads the Preferences for the Matlib
"""

import os
import json
import shutil
import hou

from amaze.core import debug
from amaze.helpers import hostos


# ---------------------------------------------------------------------------
# Portable paths across machines
#
# settings.json lives in the install folder, which multi-machine users
# sync between computers - but library/folder/favorite paths are
# absolute and machine-specific. The GENERAL rule (no folder names, no
# sync-service assumptions): store every path relative to an anchor
# every machine already knows.
#
#   * "$AMAZE/../<rest>"  - relative to the install folder, whose
#     per-machine location the package file defines. Used whenever the
#     path shares a real subtree with the install (at least
#     _MIN_COMMON_DEPTH components below the filesystem/drive root), so
#     any layout where assets travel WITH the install ports untouched.
#   * "~/<rest>"          - under the user's home folder (os.path
#     expanduser semantics, NOT Houdini's $HOME, which points at
#     Documents on Windows).
#   * absolute            - everything else; won't exist on another
#     machine, which is what the sidebar's "Locate Folder..." is for.
#
# Decode migrates a foreign absolute path by re-homing it
# (swapping another machine's /Users/<x> / C:/Users/<x> home prefix for
# this machine's) when the re-homed path actually exists. In-memory
# values are always absolute local paths; only the json is portable.

_AMAZE_TOKEN = "$AMAZE"
_MIN_COMMON_DEPTH = 2


def _amaze_root() -> str:
    return (hou.getenv("AMAZE") or "").replace("\\", "/").rstrip("/")


def _home_root() -> str:
    return os.path.expanduser("~").replace("\\", "/").rstrip("/")


def _split_dir_slash(path: str):
    """Folder prefs carry a trailing slash that prefix logic depends on;
    relpath/normpath strip it, so carry it around the transform."""
    clean = path.replace("\\", "/")
    return clean.rstrip("/"), "/" if clean.endswith("/") else ""


def _encode_path(path):
    if not isinstance(path, str) or not path:
        return path
    body, slash = _split_dir_slash(path)
    root = _amaze_root()
    home = _home_root()
    common = ""
    if root:
        try:
            common = os.path.commonpath([root, body]).replace("\\", "/")
        except ValueError:
            common = ""  # different drives (Windows) - no relative form
    under_home = bool(home) and (body == home or body.startswith(home + "/"))
    if common:
        # A shared subtree STRICTLY INSIDE home (~/AnySyncFolder/...)
        # or a sufficiently deep one outside it (/mnt/projects/...)
        # means the path travels WITH the install -> $AMAZE-relative,
        # the most portable form. A path that shares only home itself
        # (or less) with the install anchors to "~" instead: a ..-walk
        # from the install would break on a machine with a different
        # install location, while "~" survives it.
        inside_home = bool(home) and common.startswith(home + "/")
        depth = len([c for c in common.split("/") if c and ":" not in c])
        if inside_home or (not under_home and depth >= _MIN_COMMON_DEPTH):
            rel = os.path.relpath(body, root).replace("\\", "/")
            return _AMAZE_TOKEN + "/" + rel + slash
    if under_home:
        return "~" + body[len(home):] + slash
    return path


def _decode_path(path):
    if not isinstance(path, str) or not path:
        return path
    if path.startswith(_AMAZE_TOKEN):
        root = _amaze_root()
        if not root:
            return path
        body, slash = _split_dir_slash(path[len(_AMAZE_TOKEN):])
        joined = os.path.normpath(root + body).replace("\\", "/")
        return joined + slash
    if path.startswith("~"):
        body, slash = _split_dir_slash(path)
        return os.path.expanduser(body).replace("\\", "/") + slash
    clean = path.replace("\\", "/")
    if not os.path.exists(clean):
        # Foreign absolute path: swap the other machine's home prefix
        # for this machine's. The LAYOUTS live in hostos, which owns
        # every OS path convention - this file carried them as a regex,
        # which that module's docstring forbids by name.
        rehomed = hostos.rehome(clean)
        if rehomed != clean:
            debug.event("prefs", "path re-homed from another machine",
                        stored=path, resolved=rehomed)
            return rehomed
    return path


def _decode_paths(paths):
    """Decode a list of stored paths, tolerating anything else.

    load() must never RAISE - its own docstring says an exception here
    "would kill the panel during construction, with no interface and no
    message", and panel.py re-raises. Measured: `null`, `5` and `true`
    each raised TypeError straight out of load(), and a bare STRING was
    worse than a raise - "a/b" decomposed into ['a', '/', 'b'], three
    bogus folders that then reached the sidebar.
    """
    if not isinstance(paths, (list, tuple)):
        return []
    return [_decode_path(p) for p in paths if isinstance(p, str)]


def _encode_paths(paths):
    return [_encode_path(p) for p in paths]


#: The two folders a test folder is made of. Named once, because the
#: dialog, the seeder and both overlay properties all have to agree.
TEST_LIB_SUBDIR = "lib"
TEST_CACHE_SUBDIR = "cache"


def test_library_dir(folder: str) -> str:
    """The library inside a test folder, with the trailing separator
    the connectors need (they build `self._path + self._filename`)."""
    if not folder:
        return ""
    return _normalised_dir(os.path.join(folder, TEST_LIB_SUBDIR))


def test_cache_dir(folder: str) -> str:
    """The cache inside a test folder. No trailing separator: this is
    handed to `hostos.set_cache_override`, which joins onto it."""
    if not folder:
        return ""
    return os.path.join(folder, TEST_CACHE_SUBDIR).replace("\\", "/")


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
        for sub in (TEST_LIB_SUBDIR, TEST_CACHE_SUBDIR):
            path = os.path.join(folder, sub)
            if not os.path.isdir(path):
                os.makedirs(path, exist_ok=True)
                made.append(sub + "/")
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


def _default_sections() -> list:
    """Every registered section key, in tab order.

    Derived, not written out. Four copies of this list existed and two
    of them silently omitted "hip", which is how toggling any section in
    Preferences deleted the HIP tab permanently. Imported lazily so a
    prefs read never depends on the panel package being importable.
    """
    try:
        from amaze.panel import sections
        return [key for key, _label in sections.all_sections()]
    except Exception:                                    # noqa: BLE001
        # Prefs must load even if the panel package cannot import; a
        # stale default is better than no preferences at all.
        return ["material", "gradient", "cop", "code", "file"]


#: Which renderers a library shows before anyone has chosen. ONE
#: table, read by __init__ AND by load() - they used to disagree, and
#: the disagreement only showed on the path where load() returns early
#: (no settings.json at all), which is exactly a new machine.
def _through_setter(target, name, value, default):
    """Assign `value` through `name`'s validating SETTER, falling back
    to `default` when the setter rejects it.

    Both halves matter. THE SETTER, because it is where the value is
    clamped and cast, and load() bypassed six of them - a settings.json
    holding `"scroll_speed": null` loaded as None, and opening
    Preferences then ran `round(None * 100)` inside a slot, where
    PySide swallows the TypeError: the gear button simply stopped
    opening Preferences, with no message anywhere.

    AND THE GUARD, because the setters cast - `float(None)` and
    `int(None)` raise - and load() promises never to raise (practice.md
    ▸ "a config loader should degrade to unconfigured, never to an
    exception"). Routing straight through would have turned a silent
    dead button into a panel that does not build at all, which is
    worse. Same shape as the matx_parallel_downloads cast below, which
    is where the rule was written down.
    """
    try:
        setattr(target, name, value)
    except (TypeError, ValueError):
        debug.event("prefs", "unreadable %s - using the default" % name,
                    value=repr(value))
        setattr(target, name, default)


RENDERER_DEFAULTS = {
    "_renderer_matx_enabled": True,
    "_renderer_mantra_enabled": False,
    "_renderer_redshift_enabled": True,
    "_renderer_octane_enabled": True,
}

#: The settings.json key each one is stored under. Separate from the
#: attribute names because the stored keys are a contract with data on
#: disk ("renderer_materialx" predates the Karma rename) and may not
#: be tidied to match.
RENDERER_KEYS = {
    "_renderer_matx_enabled": "renderer_materialx",
    "_renderer_mantra_enabled": "renderer_mantra",
    "_renderer_redshift_enabled": "renderer_redshift",
    "_renderer_octane_enabled": "renderer_octane",
}


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


class Prefs:
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
        #: Where settings lived before that. load() migrates from here
        #: once, and leaves the original alone as a backup.
        self.legacy_path: str = hou.getenv("AMAZE") or ""
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
        # v2: registered folder pointers for the Textures section
        self._texture_folders: list[str] = []
        # v2: favorited texture files, stored as full absolute paths since
        # texture folders are arbitrary external directories with no
        # MatLib-owned id the way a material asset has
        self._texture_favorites: list[str] = []
        # v3: MATERIAL favourites, per user - asset IDS, not paths. The
        # material library was the one section whose favourite lived on
        # the SHARED record: in a multi-user library my star toggled
        # yours. The three folder sections already work this way.
        self._material_favorites: list[str] = []
        #: One-time adoption of the record-level favourites into prefs
        #: has happened for this user (see MaterialLibrary).
        self._material_favorites_adopted = False
        # v3: who this user's versions say they are by. NEVER backfilled
        # from the machine - hostos.machine_name(), platform.node,
        # getpass and $USER are all banned from this path: an
        # auto-harvested name puts a real person's identity into a
        # library that may be shared, without them choosing it. Empty
        # means versions carry no author, which is the honest default.
        self._version_author = ""
        # v2: Geometry section - registered folder pointers, favorites
        # (full paths, same reasoning as textures) and the last-selected
        # folder, mirroring the texture trio exactly.
        self._geometry_folders: list[str] = []
        self._geometry_favorites: list[str] = []
        self._last_geometry_folder = ""
        # v2: per-section "Include Subfolders" toggles (sidebar
        # right-click) - default off, matching the original flat-scan
        # design; recursion is opt-in.
        self._texture_include_subfolders = False
        self._geometry_include_subfolders = False
        # HIP (Beta): the same folder/favorite/last trio as geometry.
        # Scene thumbnails are CAPTURED, not rendered, so there is no
        # shading-mode or background preference to go with them.
        self._hip_folders: list[str] = []
        self._hip_favorites: list[str] = []
        self._last_hip_folder = ""
        self._hip_include_subfolders = False
        # The File section (the 2026-07-31 merge of Images, Geometry
        # and HIP): one folder/favorite/last/subfolders quartet. The
        # three per-section quartets above STAY - they are what an
        # older build ON THIS MACHINE still reads after a rollback,
        # and load() folds them into these once (file_section_migrated).
        # NOT the other Mac: settings.json is per-machine and does not
        # travel (INSTALL.md).
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
        # v2: favorited CURATED gradient combinations, as "<set>:<id>"
        # keys (e.g. "wada:132", "klee:7"). User gradients store their
        # favorite flag inline in gradients.json instead - they have no
        # stable id to key on here.
        # v2: last-selected folder in the Textures section - a real
        # folder path, TextureFolders.ALL_LABEL ("All") if that was
        # selected, or "" if nothing's ever been selected yet. Restored
        # both across Houdini sessions and when switching between the
        # Mat/Tex/COP tabs within one session.
        self._last_texture_folder = ""
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

    def save(self) -> None:
        """Sanitize and save the preferences to disk as json.

        REFUSES if load() could not read the existing file: this object
        is then holding pure DEFAULTS, and writing them is how "200
        gradients -> 1" happened to the settings file.
        """
        if getattr(self, "_load_failed", False):
            debug.event("prefs", "save refused - settings.json could not "
                        "be read this session", path=self.path)
            return
        self.refresh_data()
        final = self.path + "/settings.json"
        # The preferences directory may not exist yet (first run on a
        # new machine) - and it is outside the install now, so nothing
        # else guarantees it.
        try:
            os.makedirs(self.path, exist_ok=True)
        except OSError as exc:
            debug.event("prefs", "cannot create the preferences "
                        "directory", path=self.path, error=str(exc))
            return
        self._merge_settings_from_disk(final)
        # AFTER the merge: its unknown-key courtesy just setdefault-ed
        # anything the on-disk file still carries, retired keys
        # included.
        for retired in self._RETIRED_KEYS:
            self.data.pop(retired, None)
        hostos.snapshot_before_write(final)
        # A UNIQUE scratch name, not the fixed `final + ".tmp"` this used.
        # Two writers of one destination shared that single buffer and
        # interleaved into it - measured for the database case at 794
        # reads out of 1200 that PARSED while holding records from both
        # writers. settings.json has the same two-writer case: panel.py
        # constructs a Prefs per pane tab, and add_file_folder and
        # friends save from ordinary sidebar use.
        try:
            hostos.write_json_atomic(final, self.data, indent=4)
            self._remember_disk_state(final)
        except OSError as exc:
            # The only one of the package's atomic writers that recorded
            # NOTHING on failure, and none of its 21 callers wraps it -
            # so a full disk, a read-only volume or a sync conflict lost
            # every preference change in silence. You think you saved;
            # the next launch says otherwise and there is no trace of
            # why. The other writers all report; this one now matches
            # them.
            debug.event("prefs", "settings.json could not be written",
                        path=final, error=str(exc))
            debug.alert(
                "Amaze could not save your preferences.\n\n"
                "Your settings for this session still work, but they "
                "will not be there next time Houdini opens.\n\n"
                "The usual cause is a full disk or a folder Amaze is "
                "not allowed to write to:\n%s" % self.path,
                key="prefs-write-failed")

    #: Keys whose value is a LIST OF THINGS THE USER COLLECTED - folder
    #: pointers and favourites. Two panes both add one; a whole-document
    #: write from either drops the other's. These union on save; every
    #: scalar key takes this instance's value, because a scalar is a
    #: single choice and the last editor is the active one.
    _LIST_KEYS = ("texture_folders", "texture_favorites",
                  "geometry_folders", "geometry_favorites",
                  "hip_folders", "hip_favorites",
                  "file_folders", "file_favorites",
                  "material_favorites")

    #: Dict-valued collected keys merge KEY-WISE on a two-pane race:
    #: ours wins per key, theirs adopted for keys we lack - the same
    #: shape the list union has, for the same reason. EMPTY today: the
    #: location decorations (and the recursive flag) moved INSIDE
    #: `file_location_records`, which merges key-wise below with a
    #: field-wise union per record. The mechanism stays for the next
    #: dict-valued collected key.
    _DICT_KEYS: tuple = ()

    #: The BACKING ATTRIBUTE behind every collected key, and whether
    #: its list values (or dict keys) are path-encoded on disk.
    #:
    #: The merge adopts into these attributes, never into `self.data`.
    #: It wrote into `self.data` until 2026-08-02, which held for
    #: exactly one save: `save()` calls `refresh_data()` FIRST, and
    #: refresh_data rebuilds every one of these keys from the
    #: attribute, so the adopted entries were dropped on the next save
    #: from the same object - and by then `_disk_stat` matched the file
    #: this instance had just written, so the merge early-returned
    #: instead of re-adopting. Two panes, two saves, and the other
    #: pane's folders and favourites were gone for good.
    _COLLECTED_ATTRS = {
        "texture_folders": ("_texture_folders", True),
        "texture_favorites": ("_texture_favorites", True),
        "geometry_folders": ("_geometry_folders", True),
        "geometry_favorites": ("_geometry_favorites", True),
        "hip_folders": ("_hip_folders", True),
        "hip_favorites": ("_hip_favorites", True),
        "file_folders": ("_file_folders", True),
        "file_favorites": ("_file_favorites", True),
        # Asset ids, not paths - the one collected key that is not.
        "material_favorites": ("_material_favorites", False),
    }

    #: Keys this build DELIBERATELY removed. The unknown-key courtesy
    #: below keeps a NEWER build's keys alive across a save - which
    #: would also resurrect these from an older file forever, so
    #: retirement must be said out loud, not implied by absence.
    #: star_*: the star-colour rows left Preferences 2026-08-01 (the
    #: unified badge family renders the tile star as drawn).
    _RETIRED_KEYS = ("star_color_mode", "star_custom_color")

    def _remember_disk_state(self, final: str) -> None:
        self._disk_stat = hostos.disk_state(final)

    def _merge_settings_from_disk(self, final: str) -> None:
        """Fold in what another writer saved since this one read.

        settings.json had NO stale-write handling while gradients.json
        already did - and panel.py constructs a Prefs per pane tab, so
        the two-writer case is ordinary use, not an edge: pane A adds a
        texture folder, pane B changes the thumbnail size, and whichever
        saves second erases the other's whole document.

        List-valued keys union. Scalars keep this instance's value - a
        merge cannot know which single choice is newer without a clock
        it does not have, and the instance saving is the one the user is
        actually touching.
        """
        current = hostos.disk_state(final)
        if current is None or getattr(self, "_disk_stat", None) == current:
            return
        try:
            with open(final, encoding="utf-8-sig") as handle:
                theirs = json.load(handle)
        except (OSError, ValueError):
            return          # unreadable peers are load()'s business
        if not isinstance(theirs, dict):
            return
        adopted = 0
        for key in self._LIST_KEYS:
            their_list = theirs.get(key)
            if not isinstance(their_list, list):
                continue
            attr, is_path = self._COLLECTED_ATTRS[key]
            ours = getattr(self, attr, None)
            if not isinstance(ours, list):
                continue
            for value in their_list:
                if not isinstance(value, str):
                    continue
                mine = _decode_path(value) if is_path else value
                if mine not in ours:
                    ours.append(mine)
                    adopted += 1
        for key in self._DICT_KEYS:
            their_map = theirs.get(key)
            if not isinstance(their_map, dict):
                continue
            attr, is_path = self._COLLECTED_ATTRS[key]
            ours = getattr(self, attr, None)
            if not isinstance(ours, dict):
                continue
            for name, value in their_map.items():
                if not isinstance(name, str):
                    continue
                mine = _decode_path(name) if is_path else name
                if mine not in ours:
                    ours[mine] = value
                    adopted += 1
        # THE LOCATION RECORDS: key-wise - ours wins per key, theirs
        # adopted for keys we lack - and field-wise INSIDE a shared
        # record, so a label from one pane and a colour from the other
        # both survive. The four decoration keys (names / colors /
        # show_all / recursive) are DERIVED from these records by
        # refresh_data(), so this one merge keeps all four honest. The
        # old dict arms adopted the derived keys into attributes
        # refresh_data no longer reads - dead writes, the second life
        # of the 2026-08-02 bug the _COLLECTED_ATTRS docstring records
        # (found 2026-08-06).
        their_records = theirs.get("file_location_records")
        if not isinstance(their_records, dict):
            # An older build's file carries the six old keys instead.
            their_records = self._compose_location_records(theirs)
        for key, value in their_records.items():
            if not (isinstance(key, str) and isinstance(value, dict)):
                continue
            mine = _decode_path(key)
            ours_record = self._file_location_records.get(mine)
            if ours_record is None:
                self._file_location_records[mine] = dict(value)
                adopted += 1
                continue
            for field, field_value in value.items():
                if field not in ours_record:
                    ours_record[field] = field_value
                    adopted += 1
        # RE-SERIALISE. save() ran refresh_data() before calling this,
        # and refresh_data() is what turns these attributes into
        # self.data - so the adoption only reaches disk if that runs
        # again with the peer's entries now in the attributes.
        if adopted:
            self.refresh_data()
        # A key a NEWER build writes that this one does not know: keep
        # it, the same courtesy step 5 taught the load path.
        for key, value in theirs.items():
            self.data.setdefault(key, value)
        if adopted:
            debug.event("prefs", "adopted settings another writer saved",
                        adopted=adopted)

    @staticmethod
    def _compose_location_records(data: dict) -> dict:
        """`file_location_records` composed from the six old keys - the
        shape of a settings file written before 2026-08-05. Serves the
        load fallback, and the merge when the OTHER pane's file was
        written by an older build on this same machine (a rollback;
        settings.json never travels between machines, INSTALL.md)."""
        composed: dict = {}
        folders = data.get("file_folders")
        if isinstance(folders, list):
            for path in folders:
                if isinstance(path, str):
                    composed.setdefault(
                        _decode_path(path), {})["registered"] = True
        for key, field in (("file_folder_names", "name"),
                           ("file_folder_colors", "color"),
                           ("file_folder_show_all", "show_all")):
            table = data.get(key)
            if not isinstance(table, dict):
                continue
            for path, value in table.items():
                if isinstance(path, str):
                    composed.setdefault(
                        _decode_path(path), {})[field] = value
        recursive = data.get("file_recursive_folders")
        if isinstance(recursive, list):
            for path in recursive:
                if isinstance(path, str):
                    composed.setdefault(
                        _decode_path(path), {})["recursive"] = True
        return composed

    def refresh_data(self) -> dict:
        """Rebuild self.data as the EXACT dict save() serializes, and
        return it. One producer for the settings state: the debug
        engine's session snapshot records this same dict, so a
        recovery from the log is complete by construction (a
        hand-picked subset once left renderer toggles unrecoverable)."""
        # Sanitize Filepath - but an UNSET directory stays unset: the
        # old trailing-slash append turned "" into "/", and a save from
        # an unloaded Prefs then persisted the filesystem ROOT as the
        # library (live corruption, 2026-07-26).
        self._directory = self._directory.replace("\\", "/")
        if self._directory and not self._directory.endswith("/"):
            self._directory = self._directory + "/"

        self.data["directory"] = _encode_path(self._directory)
        self.data["extension"] = self._ext
        self.data["img_extension"] = self._img_ext
        self.data["img_dir"] = self._img_dir
        self.data["asset_dir"] = self._asset_dir
        self.data["rendersize"] = self._rendersize
        self.data["thumbsize"] = self._thumbsize
        self.data["thumbsize_list"] = self._thumbsize_list
        self.data["rendersamples"] = self._rendersamples
        self.data["render_on_import"] = self._render_on_import
        self.data["renderer_materialx"] = self._renderer_matx_enabled
        self.data["renderer_mantra"] = self._renderer_mantra_enabled
        self.data["renderer_redshift"] = self._renderer_redshift_enabled
        self.data["renderer_octane"] = self._renderer_octane_enabled
        self.data["show_categories"] = self._show_categories
        self.data["section_filters"] = dict(self._section_filters)
        self.data["view_mode"] = self._view_mode
        self.data["texture_folders"] = _encode_paths(self._texture_folders)
        self.data["texture_favorites"] = _encode_paths(self._texture_favorites)
        self.data["material_favorites"] = list(self._material_favorites)
        self.data["material_favorites_adopted"] = (
            self._material_favorites_adopted)
        self.data["version_author"] = self._version_author
        self.data["sidebar_counts"] = self._sidebar_counts
        self.data["ram_cache_mb"] = self._ram_cache_mb
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        self.data["test_mode"] = self._test_mode
        self.data["test_dir"] = _encode_path(self._test_dir)
        self.data["hide_empty_categories"] = self._hide_empty_categories
        self.data["enabled_sections"] = self._enabled_sections
        self.data["geometry_folders"] = _encode_paths(self._geometry_folders)
        self.data["geometry_favorites"] = _encode_paths(self._geometry_favorites)
        self.data["last_geometry_folder"] = _encode_path(self._last_geometry_folder)
        self.data["texture_include_subfolders"] = self._texture_include_subfolders
        self.data["geometry_include_subfolders"] = self._geometry_include_subfolders
        self.data["hip_folders"] = _encode_paths(self._hip_folders)
        self.data["hip_favorites"] = _encode_paths(self._hip_favorites)
        self.data["last_hip_folder"] = _encode_path(self._last_hip_folder)
        self.data["hip_include_subfolders"] = self._hip_include_subfolders
        # THE COPY, NOT THE TRUTH - and written from `_file_*`, never
        # from the public accessors, which read the library. Reading
        # them here would re-enter locations.py mid-save, and a save
        # triggered by a store write would recurse. The six old keys are
        # DERIVED from the same copy, which is what keeps an older build
        # reading a settings.json it understands after a rollback.
        records = self._file_location_records
        self.data["file_folders"] = _encode_paths(self._file_folders)
        self.data["file_favorites"] = _encode_paths(self._file_favorites)
        self.data["last_file_folder"] = _encode_path(self._last_file_folder)
        recursive = [p for p in self._file_folders
                     if records.get(p, {}).get("recursive")]
        # The retired global, written as the OR of the per-location
        # list so the one build that read it keeps a sane value.
        self.data["file_include_subfolders"] = bool(recursive)
        self.data["file_show_unknown"] = self._file_show_unknown
        self.data["file_recursive_folders"] = _encode_paths(recursive)
        self.data["file_folder_names"] = {
            _encode_path(k): v["name"] for k, v in records.items()
            if v.get("name")}
        self.data["file_folder_colors"] = {
            _encode_path(k): v["color"] for k, v in records.items()
            if v.get("color")}
        self.data["file_folder_show_all"] = {
            _encode_path(k): bool(v["show_all"]) for k, v in records.items()
            if v.get("show_all") is not None}
        self.data["file_location_records"] = {
            _encode_path(k): dict(v) for k, v in records.items()}
        self.data["path_style"] = self._path_style
        self.data["show_notes"] = self._show_notes
        self.data["notes_panel_width"] = self._notes_panel_width
        self.data["sidebar_width"] = self._sidebar_width
        self.data["geometry_shading_mode"] = self._geometry_shading_mode
        self.data["geometry_bg"] = self._geometry_bg
        self.data["icon_line_weight"] = self._icon_line_weight
        self.data["last_texture_folder"] = _encode_path(self._last_texture_folder)
        self.data["texture_parallel_conversions"] = self._texture_parallel_conversions
        self.data["accent_color"] = self._accent_color
        self.data["karma_rendersamples"] = self._karma_rendersamples
        self.data["scroll_speed"] = self._scroll_speed
        self.data["debug_mode"] = self._debug_mode
        self.data["matx_parallel_downloads"] = self._matx_parallel_downloads
        self.data["matx_resolution"] = self._matx_resolution
        return self.data

    def _migrate_from_install(self) -> None:
        """Move a pre-existing settings.json out of the install, ONCE.

        Copy, never move: the original stays where it was as a backup,
        so a user who downgrades still has it and nobody's preferences
        depend on this having worked. Anything unreadable is left
        alone - a failed migration must open the panel with defaults,
        not lose the file.
        """
        target = os.path.join(self.path, "settings.json")
        # A MARKER, not "is the target absent". The only guard used to
        # be os.path.exists(target), which makes this "every time the
        # target is missing" rather than once: delete settings.json to
        # reset your preferences, or restore a backup that did not
        # include it, and the next launch silently copied the
        # pre-2026-07-27 install copy back - resurrecting a stale
        # library path and stale favourites.
        marker = os.path.join(self.path, ".migrated-from-install")
        if os.path.exists(marker) or not self.legacy_path:
            return
        if os.path.exists(target):
            # Already migrated before this marker existed: record that
            # and stop, so the check is stable from here on.
            self._write_migration_marker(marker)
            return
        source = os.path.join(self.legacy_path, "settings.json")
        if not os.path.exists(source):
            return
        try:
            os.makedirs(self.path, exist_ok=True)
            with open(source, encoding="utf-8") as old_file:
                data = json.load(old_file)          # parse = validate
            with open(target, "w", encoding="utf-8") as new_file:
                json.dump(data, new_file, indent=4)
            self._write_migration_marker(marker)
            debug.event("prefs", "settings migrated out of the install",
                        source=source, target=target, keys=len(data))
            # The path IS named here, deliberately: this is the guide's
            # allowed case - the message is pointing the user at a file.
            # Two facts, two sentences; the backup was in a parenthesis.
            debug.note(
                "your Amaze preferences now live in %s. The old copy "
                "in the install folder is left as a backup." % target)
        except (OSError, ValueError) as exc:
            debug.event("prefs", "settings migration failed - using "
                        "defaults", source=source, error=str(exc))

    @staticmethod
    def _write_migration_marker(marker: str) -> None:
        """Best-effort: a marker that cannot be written just means the
        migration is attempted again, which is what happened before."""
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("settings were copied out of the install once\n")
        except OSError:
            pass

    def _preserve_unreadable(self, exc) -> None:
        """Keep a settings.json we could not parse, before anything
        overwrites it.

        load() returning False leaves this object holding PURE DEFAULTS,
        and the panel opens anyway - by design, so a bad settings file
        cannot cost you the whole panel. But nothing downstream can tell
        "no settings yet" from "settings we failed to read", and save()
        is unconditional: opening Preferences and closing it is enough.
        Reproduced end to end - a truncated settings.json, then one
        save(), and two registered texture folders, a favourite and a
        custom accent were gone:

            before : folders=2 favs=1 accent=#ff8800
            after  : folders=0 favs=0 accent=#5d7abd   (defaults)

        There was no recovery either: hostos.snapshot_before_write is
        once-per-session, and the marker had already been spent (fixed
        there too). So take a copy HERE, at the moment we know the file
        is both present and unparseable.

        Never overwritten once written, like .bak-first: a second failed
        load in the same session must not replace the good evidence with
        the already-defaulted rewrite.
        """
        source = self.path + "/settings.json"
        try:
            if not os.path.exists(source) or os.path.getsize(source) == 0:
                return          # nothing to preserve - a first run
            target = source + ".unreadable"
            if not os.path.exists(target):
                shutil.copy2(source, target)
            debug.note("settings.json could not be read - kept a copy",
                       source=source, target=target, error=str(exc))
            # Name the recovery that actually works. The unreadable copy
            # preserves whatever survived, but the COMPLETE state is in
            # the debug log: prefs_snapshot mirrors the saved file by
            # design and is written even with Debug Mode off, precisely
            # to be the restore source for this situation.
            # The exception, the kept path and the log path all go to the
            # log; the DIALOG carries only what the user can act on.
            # practice.md: no raw exception text on screen, and no
            # filename they have never opened unless they must touch it -
            # here they must, so the folder is named with it.
            debug.event("prefs", "settings unreadable - opened with "
                        "defaults, saving disabled", error=str(exc),
                        kept=target, log=debug.log_path())
            debug.alert(
                "Your Amaze settings could not be read, so Amaze has "
                "opened with the defaults.\n\n"
                "Nothing has been lost. Your settings file was kept "
                "untouched, and Amaze will not save over it - so your "
                "library path, folders and favourites are still there.\n\n"
                "Your settings are also recorded in the debug log. Use "
                "the Repair tool in the Amaze shelf to put them back.",
                key="prefs-unreadable")
        except OSError as copy_exc:
            debug.note("could not preserve the unreadable settings file",
                       error=str(copy_exc))

    def load(self) -> bool:
        """
        Load the Preferences from disk as json.

        Returns False when there is nothing usable to load - a missing
        file, unreadable json, or a library directory that no longer
        exists. The panel treats False as "no library configured" and
        opens anyway; an EXCEPTION here would instead kill the panel
        during construction, with no interface and no message. Every
        key is read with a default for the same reason: a settings file
        written by an older version, or hand-edited, must not be fatal.
        """
        self._migrate_from_install()
        try:
            with open(self.path + "/settings.json", encoding="utf-8") as f:
                data = json.load(f)
            # VALID JSON IS NOT VALID SETTINGS. Every key below is read
            # with .get() precisely so an old or hand-edited file is not
            # fatal - but a top level that is a list or a string has no
            # .get() at all, so it raised AttributeError straight out of
            # the constructor and took the panel with it. Exactly what
            # this function's docstring promises will not happen.
            #
            # Raised as ValueError so it joins the parse failures in the
            # handler below and gets the whole path they already have:
            # the file preserved, the write latch set, the user told.
            if not isinstance(data, dict):
                raise ValueError("top level is %s, not an object"
                                 % type(data).__name__)
            # Baseline for the stale-write merge: without it the first
            # save always re-reads, which is harmless but noisy; with a
            # wrong one it never re-reads, which is the bug. Taken from
            # the same file just read.
            self._remember_disk_state(self.path + "/settings.json")
        except FileNotFoundError:
            # ABSENT IS NOT BROKEN - the mirror image of the bug this
            # whole change is about, and it fires on a FRESH INSTALL. A
            # new machine has no settings.json, FileNotFoundError is an
            # OSError, so the handler below latched _load_failed and
            # save() then refused for the session: the library folder
            # the user picks in Preferences was never persisted, and the
            # next launch was in exactly the same state. A guard that
            # fires when there is nothing to protect is an outage.
            #
            # No _preserve_unreadable either: there is no file to
            # preserve, and it printed "could not read your settings"
            # over a first launch where nothing was wrong.
            debug.event("prefs", "no settings.json yet - opening "
                        "unconfigured", path=self.path)
            # And the latch CLEARS, exactly as a healthy read clears
            # it: the refusal is re-derived from the file on every
            # read, and an absent file is the "start fresh" route out
            # of a broken one - load() runs again when Preferences
            # closes, so a latch left set here refused every save for
            # the life of the panel.
            self._load_failed = False
            return False
        except (OSError, ValueError) as exc:
            debug.event("prefs", "settings unreadable - opening without a "
                        "library", path=self.path, error=str(exc))
            self._preserve_unreadable(exc)
            # Refuse to WRITE for the session too. Preserving a copy is
            # a mitigation; the policy is "refuse to write for the
            # session, and SAY so". gradient_library and tile_icons both
            # latch; settings.json did not, and add_file_folder and
            # friends call save() from ordinary sidebar use - so the
            # defaults reached disk without anyone opening Preferences.
            self._load_failed = True
            return False
        # A SUCCESSFUL READ CLEARS THE LATCH. It was set nowhere else and
        # cleared nowhere at all, so a repaired settings.json could never
        # be saved again for the life of this object - and the object
        # lives as long as the panel: panel.py calls this same Prefs's
        # load() again when Preferences closes and on a library switch.
        # So the sequence "launch while the file is half-synced, wait,
        # reopen Preferences" reads the file back perfectly and still
        # refuses every save, with the once-per-session line already
        # spent. The refusal is re-derived from the file on every read, so
        # clearing it here weakens nothing: a file that is still broken
        # latches again on the very next line above.
        self._load_failed = False
        # KEEP WHAT WE DID NOT READ. Every key below is pulled out with
        # .get() into a private attribute and refresh_data() then rebuilds
        # self.data from those attributes alone - so a key this build does
        # not name was simply absent from the next save, i.e. deleted.
        # Confirmed on the real machine's own settings file: 44 keys in
        # .bak-first against 49 in the current one, with
        # gradient_favorites present in one and gone from the other.
        #
        # That makes a mixed-fleet setup lossy in both directions - the
        # older build strips whatever the newer one added, on any save
        # from ordinary sidebar use - and it is the reason a new
        # preference cannot be added safely until this line exists.
        #
        # dict(data), not data: the parse result must not stay aliased
        # into a caller's document, and refresh_data() mutates this.
        self.data = dict(data)
        self._directory = _decode_path(data.get("directory", ""))
        self._ext = data.get("extension", ".mat")
        self._img_ext = data.get("img_extension", ".png")
        self._img_dir = data.get("img_dir", "img/")
        self._asset_dir = data.get("asset_dir", "mat/")
        self._rendersize = data.get("rendersize", 256)
        # .get() with a default matching ClickSlider.DEFAULT_VALUE, in
        # case settings.json predates this key (thumbsize used to be
        # required here)
        # The grid floor rose to 64 (2026-08-01), so a size saved
        # under it no longer exists. Clamp on LOAD rather than migrate
        # once: the same settings file is opened by an older build on
        # the other machine, which may write a small size back.
        self._thumbsize = max(64, min(512, int(
            data.get("thumbsize", 128) or 128)))
        # Grid and list view each remember their own icon size
        # (e.g. grid at 128 and list at 32 should coexist).
        # thumbsize stays the grid size for backward compatibility;
        # the list size defaults to the grid size the first time so
        # nothing changes visually until it's adjusted in list mode.
        self._thumbsize_list = data.get("thumbsize_list", self._thumbsize)
        self._render_on_import = data.get("render_on_import", 1)
        for _attr, _key in RENDERER_KEYS.items():
            setattr(self, _attr,
                    data.get(_key, RENDERER_DEFAULTS[_attr]))
        self._rendersamples = data.get("rendersamples", 256)
        # .get() so existing settings.json without these keys still loads
        self._show_categories = data.get("show_categories", True)
        stored = data.get("section_filters")
        if isinstance(stored, dict):
            self._section_filters = {
                str(key): str(label) for key, label in stored.items()
            }
        else:
            # Settings written before the filter menu served every
            # section: the one remembered renderer becomes Materials'
            # remembered filter, so an upgrade opens on the tab the
            # user left it on rather than silently back at All. Read,
            # never written - the old key retires with the settings
            # file it is in.
            self._section_filters = {}
            previous = data.get("last_renderer", "")
            if previous:
                self._section_filters["material"] = str(previous)
        # Through the SETTER, like the five keys the comment above
        # already names: it restricts the value to grid/list.
        _through_setter(self, "view_mode",
                        data.get("view_mode", "grid"), "grid")
        self._texture_folders = _decode_paths(
            data.get("texture_folders", [])
        )
        self._texture_favorites = _decode_paths(
            data.get("texture_favorites", [])
        )
        self._material_favorites = [
            str(x) for x in data.get("material_favorites", [])]
        self._material_favorites_adopted = bool(
            data.get("material_favorites_adopted", False))
        self._version_author = str(data.get("version_author", "") or "")
        # Through the SETTERS, not straight onto the attribute. The
        # setters exist to validate these tokens and load() bypassed
        # every one of them, so a settings.json holding
        # icon_line_weight="bold" (or a hand-edited/older-build value)
        # stayed invalid in memory - and the Preferences combos, which
        # fall back to index 0 on an unknown token, then DISPLAYED
        # something different from what was stored.
        # star_color_mode / star_custom_color once lived here; the
        # rows left Preferences with the unified badge family
        # (2026-08-01, the tile star renders as drawn). Stale keys in
        # an existing prefs file are never read, and save() drops them
        # through _RETIRED_KEYS - the unknown-key courtesy would
        # otherwise re-adopt them from disk on every write.
        self._sidebar_counts = data.get("sidebar_counts", True)
        # Through the setter: it clamps 64-4096 and casts int, and a
        # string here reaches QSpinBox.setValue and raises inside
        # the Preferences constructor.
        _through_setter(self, "ram_cache_mb",
                        data.get("ram_cache_mb", 256), 256)
        self._cache_dir = _decode_path(data.get("cache_dir", ""))
        self._test_mode = bool(data.get("test_mode", False))
        self._test_dir = _decode_path(data.get("test_dir", ""))
        self._hide_empty_categories = data.get(
            "hide_empty_categories", True
        )
        stored = data.get("enabled_sections", None)
        # A list, or the default. `None`/`"material"`/`3`/`{...}` each
        # raised out of load() below - a str via .append, the rest via
        # the `in` test - and killed the panel outright.
        self._enabled_sections = (
            [s for s in stored if isinstance(s, str)]
            if isinstance(stored, (list, tuple)) else _default_sections())
        # A section that did not exist when these settings were written
        # cannot have been DELIBERATELY disabled, so introduce it once
        # rather than leaving it invisible to everyone with saved
        # preferences. Turning it off afterwards sticks, because from
        # then on the key is present in the saved list.
        for introduced in ("file",):
            if introduced not in self._enabled_sections and \
                    "enabled_sections_seen_%s" % introduced not in data:
                self._enabled_sections.append(introduced)
            self.data["enabled_sections_seen_%s" % introduced] = True
        self._geometry_folders = _decode_paths(
            data.get("geometry_folders", [])
        )
        self._geometry_favorites = _decode_paths(
            data.get("geometry_favorites", [])
        )
        self._last_geometry_folder = _decode_path(
            data.get("last_geometry_folder", "")
        )
        self._texture_include_subfolders = data.get(
            "texture_include_subfolders", False
        )
        self._geometry_include_subfolders = data.get(
            "geometry_include_subfolders", False
        )
        self._hip_folders = _decode_paths(data.get("hip_folders", []))
        self._hip_favorites = _decode_paths(data.get("hip_favorites", []))
        self._last_hip_folder = _decode_path(data.get("last_hip_folder", ""))
        self._hip_include_subfolders = data.get(
            "hip_include_subfolders", False
        )
        self._file_folders = _decode_paths(data.get("file_folders", []))
        self._file_favorites = _decode_paths(
            data.get("file_favorites", []))
        self._last_file_folder = _decode_path(
            data.get("last_file_folder", ""))
        self._file_include_subfolders = data.get(
            "file_include_subfolders", False
        )
        self._file_show_unknown = bool(data.get("file_show_unknown", True))
        self._show_notes = bool(data.get("show_notes", False))
        try:
            self._notes_panel_width = int(
                data.get("notes_panel_width", 0) or 0)
        except (TypeError, ValueError):
            self._notes_panel_width = 0
        try:
            self._sidebar_width = int(data.get("sidebar_width", 0) or 0)
        except (TypeError, ValueError):
            self._sidebar_width = 0
        self.path_style = data.get("path_style", "home")
        names = data.get("file_folder_names", {})
        self._file_folder_names = {
            _decode_path(k): str(v)
            for k, v in names.items()
            if isinstance(k, str) and isinstance(v, str) and v
        } if isinstance(names, dict) else {}
        colors = data.get("file_folder_colors", {})
        self._file_folder_colors = {
            _decode_path(k): str(v)
            for k, v in colors.items()
            if isinstance(k, str) and isinstance(v, str) and v
        } if isinstance(colors, dict) else {}
        show_all = data.get("file_folder_show_all", {})
        self._file_folder_show_all = {
            _decode_path(k): bool(v)
            for k, v in show_all.items()
            if isinstance(k, str)
        } if isinstance(show_all, dict) else {}
        # One-time adoption of the three merged sections' collections.
        # The old keys are left EXACTLY as they were, so an older build
        # still reads them after a ROLLBACK and the two panes of one
        # session keep merging name-for-name (_LIST_KEYS unions).
        # CORRECTED 2026-08-05: this said "an older build on the other
        # machine", which settings.json cannot serve - it is per-machine
        # and does not travel between the two Macs (INSTALL.md). The
        # reasoning was inherited by section A's roadmap item and by the
        # code written from it before anyone checked. Idempotent via the
        # marker, so a favourite the user later removes stays removed.
        if not data.get("file_section_migrated", False):
            for source in (self._texture_folders, self._geometry_folders,
                           self._hip_folders):
                for path in source:
                    if path not in self._file_folders:
                        self._file_folders.append(path)
            for source in (self._texture_favorites,
                           self._geometry_favorites, self._hip_favorites):
                for path in source:
                    if path not in self._file_favorites:
                        self._file_favorites.append(path)
            self._file_include_subfolders = bool(
                self._file_include_subfolders
                or self._texture_include_subfolders
                or self._geometry_include_subfolders
                or self._hip_include_subfolders
            )
            self.data["file_section_migrated"] = True
        stored_recursive = data.get("file_recursive_folders", None)
        if isinstance(stored_recursive, list):
            self._file_recursive_folders = _decode_paths(stored_recursive)
        elif self._file_include_subfolders:
            # Seed from the retired global: recursion was on, so every
            # registered location starts recursive - nothing visibly
            # changes until the user differentiates.
            self._file_recursive_folders = list(self._file_folders)
        else:
            self._file_recursive_folders = []
        self._load_location_copy(data)
        self.icon_line_weight = data.get("icon_line_weight", "template")
        self.geometry_shading_mode = data.get(
            "geometry_shading_mode", "hiddenlineghost"
        )
        self.geometry_bg = data.get("geometry_bg", "black")
        self._last_texture_folder = _decode_path(
            data.get("last_texture_folder", "")
        )
        # Through the setter: it clamps 1-8.
        _through_setter(
            self, "texture_parallel_conversions",
            data.get("texture_parallel_conversions", 4), 4)
        # Through the setter: it guards the empty string.
        _through_setter(self, "accent_color",
                        data.get("accent_color", "#5d7abd"), "#5d7abd")
        # Through the setter: max(1, int).
        _through_setter(self, "karma_rendersamples",
                        data.get("karma_rendersamples", 9), 9)
        # Through the setter: it clamps 0.1-3.0 and casts float. A
        # settings.json holding `"scroll_speed": null` loaded as None,
        # and opening Preferences then ran round(None * 100) inside a
        # slot, where PySide swallows it - so the gear button simply
        # stopped opening Preferences, with no message anywhere.
        _through_setter(self, "scroll_speed",
                        data.get("scroll_speed", 0.75), 0.75)
        self._debug_mode = bool(data.get("debug_mode", False))
        # The ONE cast in this method, and it used to be unguarded -
        # which made it the one key that could kill the panel. load()
        # promises never to raise (every other value is read with a
        # .get() default for exactly that reason), and panel._build
        # re-raises, so the pane tab would construct NOTHING: no
        # interface, no message. Verified escaping: "abc" -> ValueError,
        # null / [] / {} -> TypeError. Reachable from a hand edit, or
        # from any future build that changes this key's type.
        try:
            self._matx_parallel_downloads = int(
                data.get("matx_parallel_downloads", 8)
            )
        except (TypeError, ValueError):
            debug.event("prefs", "unreadable matx_parallel_downloads - "
                        "using the default",
                        value=repr(data.get("matx_parallel_downloads")))
            self._matx_parallel_downloads = 8
        self.matx_resolution = data.get("matx_resolution", "2k")

        # _decode_path passes a non-str straight through, so `null`,
        # `{}` or `[]` reached os.path.exists and raised TypeError.
        if not isinstance(self._directory, str):
            self._directory = ""
        # LAST, because it needs the library path this method has only
        # just resolved. Guarded because load() must never raise - its
        # own docstring: an exception here "would kill the panel during
        # construction, with no interface and no message". A migration
        # that cannot run is a deferral, not a failure: the six old keys
        # are still written and still read, so the File section works
        # off them and the next launch tries again.
        try:
            from amaze.core import locations
            locations.migrate(self)
        except Exception as exc:                              # noqa: BLE001
            debug.event("file", "location migration could not run",
                        error=str(exc))
        if self._directory and os.path.exists(self._directory):
            return True
        return False
            # return self.get_dir_from_user(True)

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
                self._directory = hou.expandString(path)
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
        """
        if self._test_mode and self._test_dir:
            return test_library_dir(self._test_dir)
        return self._directory

    @dir.setter
    def dir(self, val: str) -> None:
        # The REAL path, always. Writing the overlay through here would
        # destroy the only route back to the real library, so the
        # Preferences rows that set it are disabled while the switch is
        # on and this stays the real field.
        self._directory = val

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
    # THE KEYS AND THE READ PROPERTIES STAY. `texture_folders`,
    # `geometry_folders` and `hip_folders` are still in older machines'
    # settings.json, `_COLLECTED_ATTRS` still round-trips them, and the
    # live-data guard still sweeps all four kinds. Nothing may strip
    # them - the same rule the retired section KEYS carry.

    @property
    def texture_folders(self) -> list[str]:
        return self._texture_folders

    @property
    def texture_favorites(self) -> list[str]:
        return self._texture_favorites

    @property
    def version_author(self) -> str:
        """The name this user's versions carry. Chosen, never harvested."""
        return self._version_author

    @version_author.setter
    def version_author(self, value: str) -> None:
        self._version_author = str(value or "").strip()

    @property
    def material_favorites(self) -> list[str]:
        return self._material_favorites

    def is_material_favorite(self, mat_id: str) -> bool:
        return str(mat_id) in self._material_favorites

    def set_material_favorite(self, mat_id: str, on: bool) -> None:
        mat_id = str(mat_id)
        if on and mat_id not in self._material_favorites:
            self._material_favorites.append(mat_id)
            self.save()
        elif not on and mat_id in self._material_favorites:
            self._material_favorites.remove(mat_id)
            self.save()

    def adopt_material_favorites(self, mat_ids: list) -> None:
        """One-time migration: the record-level favourites become this
        user's. Marked done even when empty - "nothing was starred" is
        an answer, and re-running would resurrect stars the user has
        since removed."""
        if self._material_favorites_adopted:
            return
        for mat_id in mat_ids:
            if str(mat_id) not in self._material_favorites:
                self._material_favorites.append(str(mat_id))
        self._material_favorites_adopted = True
        self.save()

    @property
    def geometry_folders(self) -> list[str]:
        return self._geometry_folders

    @property
    def geometry_favorites(self) -> list[str]:
        return self._geometry_favorites

    @property
    def hip_folders(self) -> list[str]:
        return self._hip_folders

    @property
    def hip_favorites(self) -> list[str]:
        return self._hip_favorites

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
        locations.set_record(self, old, {})
        locations.set_record(self, new, record)
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
    def last_hip_folder(self) -> str:
        return self._last_hip_folder

    @last_hip_folder.setter
    def last_hip_folder(self, val: str) -> None:
        self._last_hip_folder = str(val or "")

    @property
    def hip_include_subfolders(self) -> bool:
        return self._hip_include_subfolders

    @hip_include_subfolders.setter
    def hip_include_subfolders(self, val: bool) -> None:
        self._hip_include_subfolders = bool(val)

    @property
    def texture_include_subfolders(self) -> bool:
        return self._texture_include_subfolders

    @texture_include_subfolders.setter
    def texture_include_subfolders(self, val: bool) -> None:
        self._texture_include_subfolders = bool(val)

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
    def geometry_include_subfolders(self) -> bool:
        return self._geometry_include_subfolders

    @geometry_include_subfolders.setter
    def geometry_include_subfolders(self, val: bool) -> None:
        self._geometry_include_subfolders = bool(val)

    @property
    def last_geometry_folder(self) -> str:
        return self._last_geometry_folder

    @last_geometry_folder.setter
    def last_geometry_folder(self, val: str) -> None:
        self._last_geometry_folder = str(val or "")

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

        The TEST cache while Test Mode is on, for the same reason the
        library moves: a sabotage run that reused the real cache would
        leave its thumbnails behind in it.
        """
        if self._test_mode and self._test_dir:
            return test_cache_dir(self._test_dir)
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, val: str) -> None:
        # The REAL path, as with `dir` above.
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
    def last_texture_folder(self) -> str:
        return self._last_texture_folder

    @last_texture_folder.setter
    def last_texture_folder(self, val: str) -> None:
        self._last_texture_folder = val or ""

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

