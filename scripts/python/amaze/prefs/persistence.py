"""
Reading and writing the preferences document.

Everything that carries settings between memory and `settings.json`
lives here: the save/load round trip, the field-wise merge with what
another PANE of the same session wrote, the preservation of a file
that will not parse, and the path encoding.

`settings.json` is PER-MACHINE and never travels (INSTALL.md ▸
"settings.json NEVER travels"); it moved to the OS preferences dir on
2026-08-05, and `_merge_settings_from_disk` exists for two panes of
one session, not for two computers. The portable-path comment below
still describes the install-folder era and is left exactly as it was
found - correcting it is a separate change, not a rider on a move.

Split out of `prefs.py` 2026-08-09 (ROADMAP line 9). `Prefs` inherits
`_Persistence`, so every call site still says `prefs.save()`. The
methods moved BYTE FOR BYTE and deliberately: this file is where a
user's accumulated configuration is composed - the library pointer,
the registered locations, the favourites - and a retyped line can
change what lands on disk without anything raising.

The portable-path helpers travel WITH these methods rather than
staying behind. They are used 53 times here against twice in the rest
of `prefs.py`, and leaving them there would make this module import
`prefs.py`, which imports this one.
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

#: Read by `_decode_path` alone now. The ENCODER stopped minting this
#: form when the two encoders became one - `_MIN_COMMON_DEPTH` and the
#: second `_home_root` went with it - but every settings.json already
#: on disk carries it, and nothing migrates.
_AMAZE_TOKEN = "$AMAZE"


def _amaze_root() -> str:
    return (hou.getenv("AMAZE") or "").replace("\\", "/").rstrip("/")


def _split_dir_slash(path: str):
    """Folder prefs carry a trailing slash that prefix logic depends on;
    relpath/normpath strip it, so carry it around the transform."""
    clean = path.replace("\\", "/")
    return clean.rstrip("/"), "/" if clean.endswith("/") else ""


def _encode_path(path):
    """How settings.json spells a path on disk.

    ONE ENCODER FOR ONE RULE. `hostos.storage_path_key` already answers
    this for `locations.json` and `favourites.json`, and overview.md 4c
    says settings.json keeps a COPY of what those stores hold - so two
    encoders meant one folder could be spelled two ways in two files,
    and the copy the File section falls back to was the odd one.

    Agreement held for a folder under home and broke for one BESIDE
    the install, where a Houdini user's textures live. This side walked
    out of the install with `..` - measured on the real library,
    `~/Cloud/3D/lib/` was stored as `$AMAZE/../../../lib/` - and that
    breaks the moment the install moves, while `~` survives it. The
    walk is what goes.

    Nothing migrates: `_decode_path` reads the old spelling as well as
    the new one, so entries already on disk keep resolving and are
    rewritten only when something saves them anyway.
    """
    if not isinstance(path, str) or not path:
        return path
    return hostos.storage_path_key(path)


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


class _Persistence:
    """The save/load half of `Prefs`, mixed in.

    A MIXIN rather than a module of free functions, and the reason is
    the document rather than the code. These methods read and write
    about forty `self._*` fields that `Prefs.__init__` owns; a free
    function taking `prefs` would mean rewriting 261 references, and a
    rewrite of the code that composes `settings.json` can change what
    lands on disk without any test raising. Inheriting keeps every
    body identical to the one that has been writing this file all
    along.

    Nothing outside `Prefs` may use this class. It is not a
    preferences object - it has no state of its own and every method
    reaches into fields it does not define.
    """

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
        # Whether this write CREATES the file, asked before it does -
        # the floor is minted below. snapshot_before_write rightly
        # declines a path that is not there yet, so the first save left
        # no `.bak` tier of any kind, and load()'s absence verdict had
        # nothing to read on the one launch where it matters most.
        created = not os.path.isfile(final)
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
            if created:
                # THE FLOOR, FROM THE FIRST WRITE - the same line
                # keyed_store carries and for the reason its own
                # docstring gives. No new KIND of file: `.bak-first` is
                # already the documented immutable first-seen copy, it
                # simply arrives one write earlier so that absence is
                # answerable.
                hostos.seed_restore_floor(final)
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
    _LIST_KEYS = ("file_folders", "file_favorites", "material_favorites")

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
        "file_folders": ("_file_folders", True),
        "file_favorites": ("_file_favorites", True),
        # Asset ids, not paths - the one collected key that is not.
        "material_favorites": ("_material_favorites", False),
    }

    #: Keys this build DELIBERATELY removed. The unknown-key courtesy
    #: below keeps a NEWER build's keys alive across a save - which
    #: would also resurrect these from an older file forever, so
    #: retirement must be said out loud, not implied by absence.
    #:
    #: star_*: the star-colour rows left Preferences 2026-08-01 (the
    #: unified badge family renders the tile star as drawn).
    #:
    #: The texture/geometry/hip quartets: the File section absorbed all
    #: three on 2026-07-31 and the old keys were kept readable for a
    #: rollback until 2026-08-12. Nothing writes them now, so WITHOUT
    #: naming them here the courtesy above would setdefault them back
    #: off disk on every save and they would outlive the code forever.
    #:
    #: NOT emptied by the compatibility sweep. This is not code that
    #: serves an older BUILD - it is a cleanup that has not finished
    #: running, and settings.json is per-machine and never travels, so
    #: a machine whose file still carries these keys only drops them
    #: the next time this build saves there.
    _RETIRED_KEYS = (
        "star_color_mode", "star_custom_color",
        "texture_folders", "texture_favorites", "last_texture_folder",
        "texture_include_subfolders",
        "geometry_folders", "geometry_favorites", "last_geometry_folder",
        "geometry_include_subfolders",
        "hip_folders", "hip_favorites", "last_hip_folder",
        "hip_include_subfolders",
        "file_section_migrated",
        # Retired into `library_user`, which is the ONE identity now -
        # it keys the per-user things AND signs versions. load() adopts
        # the value first, so naming it here drops the key without
        # dropping the name (ROADMAP line 21).
        "version_author",
    )

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
        # THE SAME TABLE THE LOAD WALKS. These four were written out by
        # hand here, spelling each stored key a third time - so a fifth
        # renderer added to RENDERER_KEYS and RENDERER_DEFAULTS would
        # load correctly and never be written back. No exception, no
        # red test: the value would simply reset every session.
        for attribute, stored_key in RENDERER_KEYS.items():
            self.data[stored_key] = getattr(self, attribute)
        self.data["show_categories"] = self._show_categories
        self.data["section_filters"] = dict(self._section_filters)
        self.data["view_mode"] = self._view_mode
        self.data["material_favorites"] = list(self._material_favorites)
        self.data["library_user"] = self._library_user
        self.data["sidebar_counts"] = self._sidebar_counts
        self.data["ram_cache_mb"] = self._ram_cache_mb
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        self.data["test_mode"] = self._test_mode
        self.data["test_dir"] = _encode_path(self._test_dir)
        self.data["hide_empty_categories"] = self._hide_empty_categories
        self.data["enabled_sections"] = self._enabled_sections
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
        self.data["texture_parallel_conversions"] = self._texture_parallel_conversions
        self.data["accent_color"] = self._accent_color
        self.data["karma_rendersamples"] = self._karma_rendersamples
        self.data["scroll_speed"] = self._scroll_speed
        self.data["debug_mode"] = self._debug_mode
        self.data["matx_parallel_downloads"] = self._matx_parallel_downloads
        self.data["matx_resolution"] = self._matx_resolution
        return self.data

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
        try:
            with open(self.path + "/settings.json",
                      encoding="utf-8-sig") as f:
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
            # NO ABSENT-BUT-KNOWN VERDICT HERE, deliberately, and it is
            # the one guarded store that must not have one. The
            # databases latch on absence because a library is SHARED and
            # a file can be late; settings.json is per-machine and never
            # travels (INSTALL.md ▸ preferences are machine-local), so
            # there is no late case to protect against - while deleting
            # this file IS the prescribed way out of an unreadable one,
            # and a trace-based latch would refuse the fresh start it
            # offers. The `.unreadable` copy the refusal leaves behind
            # would be exactly that trace.
            #
            # The latch CLEARS, exactly as a healthy read clears it: the
            # refusal is re-derived from the file on every read, and
            # load() runs again when Preferences closes, so a latch left
            # set here refused every save for the life of the panel.
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
        self._material_favorites = [
            str(x) for x in data.get("material_favorites", [])]
        self._library_user = str(data.get("library_user", "") or "").strip()
        if not self._library_user:
            # ADOPTED, not defaulted. An install that has been signing
            # versions as `Plum` keeps BEING Plum, so every `Plum-<n>`
            # stem already on disk still matches its writer and nothing
            # is renamed. The other machine's own name becomes a second
            # row in the user dropdown - an unused name is a row to
            # pick from, not lost data (ROADMAP line 21).
            #
            # Reading a RETIRED key is not compatibility work: this is
            # the one pass that carries the value forward, and after the
            # next save the old key is gone (`_RETIRED_KEYS`).
            self._library_user = str(
                data.get("version_author", "") or "").strip()
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

