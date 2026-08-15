"""
Reading and writing the preferences document.

What carries settings between memory and disk lives here: the
save/load round trip, WHAT a stored key means, the path encoding - and
the shared eighteen's trips to the LIBRARY (`SHARED_KEYS`,
`_adopt_shared`, `_push_shared`): their truth is the library's
`prefs.json`, and `settings.json` keeps them only as the last-known
`shared_settings` copy.

THE GUARDS ARE THE KEYED STORE ENGINE'S. settings.json is a registered
store - `keyed_store.SETTINGS`, declared there, normaliser bound here -
so the read verdict, the unreadable latch, the peer fold, the atomic
write, the snapshot tier and what a denied write owes the user are
written once and proved once. What stays here is what only this module
can know: which keys exist, what each may hold, and which this build
has retired. ▸p/store-guards

The FILE `settings.json` is PER-MACHINE and never travels - no sync
folder, no merge between computers, and the fold is for two panes of
one session.

`Prefs` inherits `_Persistence`, so every call site still says
`prefs.save()`. The portable-path helpers live here rather than in
`prefs.py`: they are used 53 times here against twice there, and the
other way round would make this module import its own importer.
"""

import os
import hou

from amaze.core import debug, keyed_store
from amaze.helpers import hostos


def _settings_value(value):
    """A settings VALUE, as the engine sees one.

    Anything json can hold is a legitimate setting, so this keeps what
    it is handed. WHAT a key may hold is checked one key at a time by
    the typed readers in `load()`, each with a default
    (`_through_setter`) - never at the store boundary, because a
    boundary that judged them would have to know all sixty-four and
    would silently drop the one it had not been told about. That is the
    unknown-key courtesy, and it is the reason this file survives a
    mixed fleet at all.

    `None` is the one refusal, and it costs nothing: the store declares
    `falsy_is_a_value`, so None is how a normaliser says no, and a null
    preference means exactly what a missing one means - both reach
    `_through_setter` and become the default.
    """
    return value


#: settings.json through the KEYED STORE ENGINE (ROADMAP line 26). The
#: declaration is in `keyed_store` with the other five, so enumerating
#: the guarded files costs no import of Houdini; only the normaliser
#: lives here, with the module that knows what a setting is.
SPEC = keyed_store.bind(keyed_store.SETTINGS, _settings_value)


# ---------------------------------------------------------------------------
# Portable paths across machines
#
# A stored path must survive the install MOVING - and, if a settings
# file is ever copied by hand, landing on a machine whose home folder
# is spelled differently. (This used to say settings.json lives in the
# install folder and syncs between computers; it moved to the OS
# preferences dir on 2026-08-05 and never travels.) The general rule,
# with no folder names and no sync-service assumptions: store every
# path relative to an anchor every machine already knows.
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
    "_renderer_redshift_enabled": True,
    "_renderer_octane_enabled": True,
}

#: The settings.json key each one is stored under. Separate from the
#: attribute names because the stored keys are a contract with data on
#: disk ("renderer_materialx" predates the Karma rename) and may not
#: be tidied to match.
RENDERER_KEYS = {
    "_renderer_matx_enabled": "renderer_materialx",
    "_renderer_redshift_enabled": "renderer_redshift",
    "_renderer_octane_enabled": "renderer_octane",
}
#: `renderer_mantra` was the fourth until 2026-08-14. It is not
#: migrated away: a library's `prefs.json` written before then still
#: holds that record, and the store only reads keys something
#: declares, so it sits unread rather than being read as a renderer
#: nothing supports. Nothing may re-declare that spelling.

#: THE SHARED EIGHTEEN (ROADMAP line 22): the keys whose truth is the
#: LIBRARY's `prefs.json`, one answer for everyone who opens it.
#: stored key -> (property, attribute); a None property is a
#: read-only layout value with no setter, adopted straight onto the
#: attribute. ONE table, walked by load(), refresh_data(), the adopt
#: and the push - the RENDERER_KEYS lesson one block up: a key added
#: to one walker and not the others loads correctly and silently
#: never travels.
SHARED_KEYS = {
    "extension": (None, "_ext"),
    "img_extension": (None, "_img_ext"),
    "img_dir": (None, "_img_dir"),
    "asset_dir": (None, "_asset_dir"),
    "rendersize": ("rendersize", "_rendersize"),
    "rendersamples": ("rendersamples", "_rendersamples"),
    "karma_rendersamples":
        ("karma_rendersamples", "_karma_rendersamples"),
    "render_on_import": ("render_on_import", "_render_on_import"),
    "matx_resolution": ("matx_resolution", "_matx_resolution"),
    "ram_cache_mb": ("ram_cache_mb", "_ram_cache_mb"),
    "matx_parallel_downloads":
        ("matx_parallel_downloads", "_matx_parallel_downloads"),
    "texture_parallel_conversions":
        ("texture_parallel_conversions",
         "_texture_parallel_conversions"),
    "geometry_shading_mode":
        ("geometry_shading_mode", "_geometry_shading_mode"),
    "geometry_bg": ("geometry_bg", "_geometry_bg"),
    "path_style": ("path_style", "_path_style"),
}
SHARED_KEYS.update({
    stored: (attr[1:], attr) for attr, stored in RENDERER_KEYS.items()})

#: Sections introduced after settings existed: absent from a saved
#: list without its seen flag means the list predates the section
#: rather than a deliberate OFF - introduced once, flag set.
_INTRODUCED_SECTIONS = ("file",)

#: THE PER-USER SCALARS (ROADMAP line 22): one user's view state on
#: THIS machine, under `users.<uid>` in settings.json. stored key ->
#: (property, attribute, default). The default is the reset a user
#: switch applies for keys the incoming block does not carry; a test
#: derives its agreement with __init__. Four more per-user keys are
#: handled beside every walk of this table because each has a nuance a
#: uniform walk cannot carry: `thumbsize` (the 64-512 load clamp),
#: `thumbsize_list` (defaults to the grid size), `last_file_folder`
#: (path-encoded on disk), `section_filters` (a dict with a legacy
#: fallback) and `enabled_sections` (a list plus the introduction).
USER_KEYS = {
    "view_mode": ("view_mode", "_view_mode", "grid"),
    "sidebar_width": ("sidebar_width", "_sidebar_width", 0),
    "notes_panel_width":
        ("notes_panel_width", "_notes_panel_width", 0),
    "show_notes": ("show_notes", "_show_notes", False),
    "show_categories": ("show_categories", "_show_categories", True),
    "sidebar_counts": ("sidebar_counts", "_sidebar_counts", True),
    "hide_empty_categories":
        ("hide_empty_categories", "_hide_empty_categories", True),
    "scroll_speed": ("scroll_speed", "_scroll_speed", 0.75),
    "accent_color": ("accent_color", "_accent_color", "#5d7abd"),
    "icon_line_weight":
        ("icon_line_weight", "_icon_line_weight", "template"),
    "file_show_unknown":
        ("file_show_unknown", "_file_show_unknown", True),
    "debug_mode": ("debug_mode", "_debug_mode", False),
}

#: Every per-user spelling that leaves the flat document once a user
#: exists to carry it - the conditional half of retirement, because
#: the flat shape IS the store while nobody is picked. The three
#: last-known File copies ride here too: what they mirror is per-user.
USER_RETIRED = tuple(USER_KEYS) + (
    "thumbsize", "thumbsize_list", "last_file_folder",
    "section_filters", "enabled_sections",
    "file_folders", "file_favorites", "file_location_records") + tuple(
    "enabled_sections_seen_%s" % s for s in _INTRODUCED_SECTIONS)


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

    def _settings_store(self, reread: bool = False):
        """This machine's settings, through the engine.

        THIS OBJECT'S OWN, never the shared cache. panel.py builds a
        Prefs per pane tab and the two hold different view state, so
        the baseline deciding whether to re-read the other's write has
        to be per HOLDER (`keyed_store.own_store`).
        """
        store = getattr(self, "_settings_handle", None)
        # The configuration directory is read off this object, so a
        # handle minted against a different one is a handle on the
        # wrong file.
        if store is None or store.path != os.path.join(
                str(self.path), keyed_store.SETTINGS):
            store = keyed_store.own_store(SPEC, self)
            self._settings_handle = store
        elif reread:
            store.reread()
        return store

    @property
    def _load_failed(self) -> bool:
        """THE ENGINE'S LATCH, read rather than kept (ROADMAP line 26).

        This was a flag set in three branches of `load()` and cleared in
        two, and the bug it kept producing was a stale one: a repaired
        settings.json could not be saved for the life of the object
        because nothing cleared it, and later, a fresh install latched
        it on a file that had simply never existed. It is DERIVED now -
        the store re-decides on every read, so there is no third place
        that can forget to move it.
        """
        try:
            return not self._settings_store().writable
        except (ValueError, AttributeError):
            # A Prefs that cannot say where its configuration lives has
            # no store to ask - and no file it could have failed to
            # read, so nothing is latched.
            return False

    def save(self) -> None:
        """Sanitize and save the preferences to disk as json.

        REFUSES if the store could not read the existing file: this
        object is then holding pure DEFAULTS. Asked BEFORE
        `_push_shared`, because the same refusal has to protect the
        LIBRARY - eighteen defaulted values pushed into everyone's
        `prefs.json` is the same accident one scope out.
        """
        store = self._settings_store()
        if not store.writable:
            debug.event("prefs", "save refused - settings.json could not "
                        "be read this session", path=self.path)
            return
        # The shared eighteen go to the LIBRARY first - one batch
        # write that collapses to nothing when no shared key moved -
        # so the document composed below only ever carries the copy.
        self._push_shared()
        self.refresh_data()
        # RETIREMENT IS SAID OUT LOUD, and the engine drops these AFTER
        # it has adopted what the file still carries. Sweeping
        # `self.data` here instead looks identical and does nothing
        # (practice.md > A DOCUMENT IS NOT A TABLE OF ROWS, point 3).
        retire = list(self._RETIRED_KEYS)
        # The per-user spellings retire only once a user EXISTS to
        # carry them - flat while nobody, block once somebody - so a
        # userless session keeps full persistence in the old shape and
        # the migration source survives until the migration can run.
        if self._library_user:
            retire.extend(USER_RETIRED)
        # The whole guard set is the engine's from here - atomic write,
        # snapshot tier, write-once floor, peer fold, foreign entries,
        # and the report a denied write owes the user.
        if store.replace(self.data, retire=retire):
            self._absorb_committed(store)

    def _absorb_committed(self, store) -> None:
        """The committed document back into the attributes.

        THE FOLD HAPPENS AT WRITE TIME, and the attributes are what the
        panel paints from - so a fold that reached only the bytes would
        leave the other pane's folder missing from this pane's sidebar
        until Houdini restarted (practice.md > A DOCUMENT IS NOT A
        TABLE OF ROWS, point 4).

        ONLY THE COLLECTED KEYS: the scalars are this pane's own and
        the fold never moves them.
        """
        self.data = store.everyones()
        stored = self.data.get("users")
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        # Where the three live depends on whether anybody is picked -
        # inside the block once somebody is, flat while nobody is - and
        # both shapes are live, so both are read.
        block = (self._users_blocks.get(self._library_user, {})
                 if self._library_user else {})

        def committed(key):
            value = block.get(key)
            return self.data.get(key) if value is None else value

        folders = committed("file_folders")
        if isinstance(folders, list):
            self._file_folders = _decode_paths(folders)
        favourites = committed("file_favorites")
        if isinstance(favourites, list):
            self._file_favorites = _decode_paths(favourites)
        records = committed("file_location_records")
        if isinstance(records, dict):
            self._file_location_records = {
                _decode_path(key): dict(value)
                for key, value in records.items()
                if isinstance(key, str) and isinstance(value, dict)}

    # WHICH KEYS COLLECT RATHER THAN OVERWRITE is the STORE's
    # declaration now (`keyed_store.SETTINGS` > `merge_rules`), not
    # three tables here. The three could only spell a TOP-LEVEL key,
    # which the per-user migration silently broke by moving every
    # collected key under `users/<uid>/` (practice.md > A DOCUMENT IS
    # NOT A TABLE OF ROWS, point 2). `_absorb_committed` reads the
    # folded document back into the attributes they fed.

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

    #: The shared eighteen's flat spellings retire WITH their values
    #: safe: the same save that pops these writes them into the
    #: `shared_settings` copy and pushes them to the library. Derived
    #: from the one table so a twentieth shared key cannot be retired
    #: in one place and forgotten in the other.
    #:
    #: The five location-decoration spellings retire UNCONDITIONALLY:
    #: they were the location record in an older shape, derived
    #: outputs rather than migration sources, and the record in
    #: `file_location_records` (and the library's own store) is the
    #: one home. Kept for a same-machine rollback until 2026-08-14,
    #: which pre-1.0 is not owed.
    _RETIRED_KEYS = _RETIRED_KEYS + tuple(SHARED_KEYS) + (
        "file_folder_names", "file_folder_colors",
        "file_folder_show_all", "file_recursive_folders",
        "file_include_subfolders")

    # THE STALE-WRITE BASELINE is the store's `_disk_state` now. It was
    # `_disk_stat` here, remembered in two places and compared in a
    # third, and the store already keeps exactly this fingerprint
    # through the same `hostos.disk_state` call.

    # -- the shared eighteen (ROADMAP line 22, stage D) -----------------

    def _adopt_shared(self) -> None:
        """Fold the library's shared settings over the attributes.

        Runs at the two moments a Prefs meets a library - load() and
        the `dir` setter - and both come BEFORE any user edit in every
        real flow, so an adopted value can never eat an edit. Reads
        stay plain attribute reads; this is what keeps them true to
        the library without a store round-trip per read.

        Values route through the same validation load() uses: the
        store types the RECORD, not the value's meaning, so a
        hand-edited store can hold a string where a size belongs.
        """
        directory = self.dir
        if not directory or not os.path.isdir(directory):
            return
        from amaze.core import library_prefs
        values = library_prefs.all_values(self)
        if not values:
            return          # fresh, latched or empty - the copy holds
        for stored, (prop, attr) in SHARED_KEYS.items():
            if stored not in values:
                continue
            value = values[stored]
            if prop is None:
                # The layout quartet has no setters - read-only
                # properties over strings the connector composes paths
                # from, so only a string may land.
                if isinstance(value, str):
                    setattr(self, attr, value)
            else:
                _through_setter(self, prop, value,
                                getattr(self, attr, None))

    def _push_shared(self) -> None:
        """Carry the attributes into the library's store - ONE write.

        Gated the way locations gates: with no library directory the
        engine would write a relative path into the CWD, and a latched
        store must keep its evidence. A refused or skipped push loses
        nothing - the `shared_settings` copy keeps the session's
        values and the next reachable save retries them.
        """
        directory = self.dir
        if not directory or not os.path.isdir(directory):
            return
        from amaze.core import library_prefs
        if not library_prefs.takes_writes(self):
            return
        library_prefs.set_values(self, {
            stored: getattr(self, attr)
            for stored, (_prop, attr) in SHARED_KEYS.items()})

    # -- the per-user eighteen (ROADMAP line 22, stage D) ---------------

    def _user_state_document(self) -> dict:
        """The current per-user state as its stored keys - ONE
        composer for the block branch, the flat branch and the switch
        snapshot, so the three cannot drift apart."""
        out = {stored: getattr(self, attr)
               for stored, (_prop, attr, _default) in USER_KEYS.items()}
        out["thumbsize"] = self._thumbsize
        out["thumbsize_list"] = self._thumbsize_list
        out["last_file_folder"] = _encode_path(self._last_file_folder)
        out["section_filters"] = dict(self._section_filters)
        out["enabled_sections"] = list(self._enabled_sections)
        out.update(self._sections_seen)
        # THE LAST-KNOWN COPIES, NOT THE TRUTH - written from the
        # private fields, never the public accessors, which read the
        # library; reading them here would re-enter locations.py
        # mid-save, and a save triggered by a store write would
        # recurse. What they mirror is per-user, so they ride with the
        # user's other state.
        out["file_folders"] = _encode_paths(self._file_folders)
        out["file_favorites"] = _encode_paths(self._file_favorites)
        out["file_location_records"] = {
            _encode_path(k): dict(v)
            for k, v in self._file_location_records.items()}
        return out

    def _apply_user_block(self, block: dict, data: dict) -> None:
        """The per-user reads, one body for load() and the user
        switch: block first, flat as the migration-source fallback,
        the default last - through the validating setters, because a
        block is as hand-editable as the file around it."""
        def stored_value(key, default):
            return block.get(key, data.get(key, default))

        for stored, (prop, _attr, default) in USER_KEYS.items():
            _through_setter(self, prop, stored_value(stored, default),
                            default)
        # The 64-512 clamp holds on every APPLY: an older build on the
        # other machine may write a size under the risen grid floor.
        try:
            self._thumbsize = max(64, min(512, int(
                stored_value("thumbsize", 128) or 128)))
        except (TypeError, ValueError):
            self._thumbsize = 128
        # The list size defaults to the grid size until adjusted.
        _through_setter(self, "thumbsize_list",
                        stored_value("thumbsize_list", self._thumbsize),
                        self._thumbsize)
        self._last_file_folder = _decode_path(
            str(stored_value("last_file_folder", "") or ""))
        stored = stored_value("section_filters", None)
        if isinstance(stored, dict):
            self._section_filters = {
                str(key): str(label) for key, label in stored.items()
            }
        else:
            # Settings written before the filter menu served every
            # section: the one remembered renderer becomes Materials'
            # remembered filter, so an upgrade opens on the tab the
            # user left it on rather than silently back at All. Read,
            # never written - the old key retires with the flat shape.
            self._section_filters = {}
            previous = data.get("last_renderer", "")
            if previous:
                self._section_filters["material"] = str(previous)
        self._file_folders = _decode_paths(
            stored_value("file_folders", []))
        self._file_favorites = _decode_paths(
            stored_value("file_favorites", []))
        # The last-known location records: the copy the File section
        # serves when the library is unreachable. Only the dict shape
        # counts; the five derived spellings it used to be composed
        # from are retired outright.
        stored = stored_value("file_location_records", None)
        self._file_location_records = {
            _decode_path(key): dict(value)
            for key, value in stored.items()
            if isinstance(key, str) and isinstance(value, dict)
        } if isinstance(stored, dict) else {}
        stored = stored_value("enabled_sections", None)
        # A list, or the default. `None`/`"material"`/`3`/`{...}` each
        # raised out of load() - a str via .append, the rest via the
        # `in` test - and killed the panel outright.
        self._enabled_sections = (
            [s for s in stored if isinstance(s, str)]
            if isinstance(stored, (list, tuple)) else _default_sections())
        # A section that did not exist when this user's state was
        # written cannot have been DELIBERATELY disabled, so introduce
        # it once. Turning it off afterwards sticks, because from then
        # on the seen flag rides with the state.
        self._sections_seen = {}
        for introduced in _INTRODUCED_SECTIONS:
            seen_key = "enabled_sections_seen_%s" % introduced
            if introduced not in self._enabled_sections and \
                    not stored_value(seen_key, False):
                self._enabled_sections.append(introduced)
            self._sections_seen[seen_key] = True

    def _switch_user_state(self, old: str, new: str) -> None:
        """Change WHOSE view state the attributes describe.

        The invariant every walk of USER_KEYS leans on: the flat
        attributes always describe the CURRENT user. So a switch
        snapshots them into the old user's block first, then applies
        the new user's block over the defaults - and a new user with
        no block on this machine inherits what is on screen instead,
        which is what makes the first mint and a second machine's
        first pick keep the arrangement being looked at.
        """
        if old:
            block = dict(self._users_blocks.get(old, {}))
            block.update(self._user_state_document())
            self._users_blocks[old] = block
        if not new:
            return
        block = self._users_blocks.get(new)
        if block is None:
            return
        self._apply_user_block(dict(block), {})

    # `_merge_settings_from_disk` STOOD HERE and is the engine's now
    # (ROADMAP line 26, stage 4). It answered the same question
    # `Store._adopt_from_disk` answers - a peer wrote since I read, what
    # do I write - step for step: a `hostos.disk_state` stamp, a
    # re-read, adopt what we lack, ours wins, no tombstones, count and
    # log. What it added was the UNIT: lists that combine, scalars where
    # the saving pane wins, records merged field by field. That is
    # `Spec.merge_rules` on the declaration, and the engine's fold reads
    # it.
    #
    # It also had a defect this move fixes rather than carries. Its
    # `their_value` helper looked inside the peer's `users.<uid>` block
    # for the three collected keys, but the ADOPTION wrote into flat
    # attributes and `_DICT_KEYS`/`_LIST_KEYS` named only top-level
    # spellings - so the shape it was reading and the shape it was
    # writing had drifted apart in the per-user migration. The rules
    # spell the nesting out (`users/*/file_folders`) and the fold walks
    # to it.

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
        # THE SHARED EIGHTEEN ARE THE LIBRARY'S (ROADMAP line 22).
        # What is written HERE is the last-known COPY, one dict under
        # one key, serving the next session when the library is
        # unreachable. The truth goes through _push_shared(); the flat
        # spellings are in _RETIRED_KEYS so an old file's keys cannot
        # ride the unknown-key courtesy back in.
        self.data["shared_settings"] = {
            stored: getattr(self, attr)
            for stored, (_prop, attr) in SHARED_KEYS.items()}
        self.data["library_user"] = self._library_user
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        self.data["test_mode"] = self._test_mode
        self.data["test_dir"] = _encode_path(self._test_dir)
        # THE PER-USER EIGHTEEN: flat while nobody, block once
        # somebody. With no user picked this writes the old flat shape
        # whole - a session that cancelled the ASK dialog keeps full
        # persistence and nothing is filed under nobody. With a user,
        # the same composition lands in their block (over what the
        # block already carried, so a newer build's block keys
        # survive) and save() retires the flat spellings.
        if self._library_user:
            block = dict(self._users_blocks.get(self._library_user, {}))
            block.update(self._user_state_document())
            self._users_blocks[self._library_user] = block
        else:
            self.data.update(self._user_state_document())
        self.data["users"] = {
            uid: dict(block)
            for uid, block in self._users_blocks.items()}
        return self.data

    # `_preserve_unreadable` STOOD HERE, and the behaviour it earned
    # SURVIVES WHOLE - resilience outranks (practice.md), and that copy
    # is what a truncated settings file is recovered from. It is
    # `hostos.preserve_unreadable`, called by `Store._load` at the same
    # moment for the same reason, with the same write-once rule and the
    # same 0-byte refusal; its WORDS are the spec's `unreadable_alert`
    # under the same `prefs-unreadable` key, so nothing about what the
    # user sees has moved.
    #
    # What it was reproduced against stays worth stating, because it is
    # what the guard is for: a truncated settings.json, then one save,
    # and two registered folders, a favourite and a custom accent were
    # gone - `folders=2 favs=1 accent=#ff8800` before,
    # `folders=0 favs=0 accent=#5d7abd` after, pure defaults written
    # over a file nobody could read.

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
        # RE-READ ON PURPOSE. panel.py calls this same Prefs's load()
        # again when Preferences closes and on a library switch, and its
        # whole job is to answer with what is on DISK - so the cached
        # table is dropped and the file parsed again. Everything this
        # did inline is the store's now: the parse, the BOM, the
        # wrong-shape guard that stops a top-level list or string
        # raising AttributeError out of the constructor, the
        # `.unreadable` copy, the alert, and the write latch.
        store = self._settings_store(reread=True)
        if store.state == keyed_store.FRESH:
            # ABSENT IS NOT BROKEN, and it fires on a FRESH INSTALL: a
            # new machine has no settings.json, and a guard that latched
            # here meant the library folder the user picks in
            # Preferences was never persisted - the next launch in
            # exactly the same state.
            #
            # NO ABSENT-BUT-KNOWN VERDICT, deliberately, and this is the
            # one guarded store that must not have one - the store says
            # so as `absence_is_fresh`. The databases latch on absence
            # because a library is SHARED and a file can be late;
            # nothing is late on this machine's own disk, deleting this
            # file IS the prescribed way out of an unreadable one, and
            # the `.unreadable` copy that refusal leaves behind is
            # itself one of the traces the guard reads.
            debug.event("prefs", "no settings.json yet - opening "
                        "unconfigured", path=self.path)
            return False
        if not store.writable:
            # The file is there and will not parse. The engine has
            # already kept the copy and told the user; refusing to WRITE
            # for the session is the other half, and it is the store's
            # state rather than a flag - re-derived on every read, so a
            # repaired file saves again without anything having to
            # remember to clear it.
            debug.event("prefs", "settings unreadable - opening without a "
                        "library", path=self.path, trace=store.trace)
            return False
        data = store.everyones()
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
        # The shared eighteen load from the last-known COPY, falling
        # back to the flat spelling an older file carries - the
        # migration source, popped by the same save that writes the
        # copy. The library's own answer lands over all of these at
        # the adopt below.
        shared = data.get("shared_settings")
        if not isinstance(shared, dict):
            shared = {}
        # WHO, before any per-user read: the identity picks which
        # users.<uid> block the eighteen load from.
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
        # THE PER-USER DIMENSION (ROADMAP line 22): per-UID blocks of
        # this machine's per-user keys. Junk shapes are dropped the way
        # _decode_paths drops them - load() may not raise, and
        # refresh_data() rewrites the key from this attribute, so junk
        # in the file dies on the next save instead of riding the
        # unknown-key courtesy forever.
        stored = data.get("users")
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        # The eighteen per-user reads, one body shared with the user
        # switch: the active block first, flat as the migration
        # fallback, defaults last.
        self._apply_user_block(
            self._users_blocks.get(self._library_user, {}), data)
        self._directory = _decode_path(data.get("directory", ""))
        self._ext = shared.get("extension", data.get("extension", ".mat"))
        self._img_ext = shared.get(
            "img_extension", data.get("img_extension", ".png"))
        self._img_dir = shared.get("img_dir", data.get("img_dir", "img/"))
        self._asset_dir = shared.get(
            "asset_dir", data.get("asset_dir", "mat/"))
        self._rendersize = shared.get(
            "rendersize", data.get("rendersize", 256))
        self._render_on_import = shared.get(
            "render_on_import", data.get("render_on_import", 1))
        for _attr, _key in RENDERER_KEYS.items():
            setattr(self, _attr,
                    shared.get(_key,
                               data.get(_key, RENDERER_DEFAULTS[_attr])))
        self._rendersamples = shared.get(
            "rendersamples", data.get("rendersamples", 256))
        # `material_favorites` is deliberately NOT loaded onto the
        # object: `locations.migrate_asset_favourites` reads it out of
        # `data` and pops it once every id is proven in the library's
        # favourites store. An attribute here would write the key back
        # on the next save and undo the pop.
        #
        # star_color_mode / star_custom_color once loaded here; the
        # rows left Preferences with the unified badge family
        # (2026-08-01, the tile star renders as drawn). Stale keys in
        # an existing prefs file are never read, and save() drops them
        # through _RETIRED_KEYS - the unknown-key courtesy would
        # otherwise re-adopt them from disk on every write.
        # Through the setter: it clamps 64-4096 and casts int, and a
        # string here reaches QSpinBox.setValue and raises inside
        # the Preferences constructor.
        _through_setter(self, "ram_cache_mb",
                        shared.get("ram_cache_mb",
                                   data.get("ram_cache_mb", 256)), 256)
        self._cache_dir = _decode_path(data.get("cache_dir", ""))
        self._test_mode = bool(data.get("test_mode", False))
        self._test_dir = _decode_path(data.get("test_dir", ""))
        self.path_style = shared.get(
            "path_style", data.get("path_style", "home"))
        self.geometry_shading_mode = shared.get(
            "geometry_shading_mode",
            data.get("geometry_shading_mode", "hiddenlineghost"))
        self.geometry_bg = shared.get(
            "geometry_bg", data.get("geometry_bg", "black"))
        # Through the setter: it clamps 1-8.
        _through_setter(
            self, "texture_parallel_conversions",
            shared.get("texture_parallel_conversions",
                       data.get("texture_parallel_conversions", 4)), 4)
        # Through the setter: max(1, int).
        _through_setter(self, "karma_rendersamples",
                        shared.get("karma_rendersamples",
                                   data.get("karma_rendersamples", 9)), 9)
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
                shared.get("matx_parallel_downloads",
                           data.get("matx_parallel_downloads", 8))
            )
        except (TypeError, ValueError):
            debug.event("prefs", "unreadable matx_parallel_downloads - "
                        "using the default",
                        value=repr(data.get("matx_parallel_downloads")))
            self._matx_parallel_downloads = 8
        self.matx_resolution = shared.get(
            "matx_resolution", data.get("matx_resolution", "2k"))

        # _decode_path passes a non-str straight through, so `null`,
        # `{}` or `[]` reached os.path.exists and raised TypeError.
        if not isinstance(self._directory, str):
            self._directory = ""
        # The library's shared settings land OVER the copy just read -
        # load() is one of the two moments a Prefs meets a library
        # (the dir setter is the other), and both precede any user
        # edit. A pure read: nothing here writes the library.
        self._adopt_shared()
        # NO MIGRATION RUNS HERE, deliberately (2026-08-13). load()
        # used to end by calling `locations.migrate`, and briefly
        # `migrate_asset_favourites` too - and both WRITE THE LIBRARY,
        # which made every caller of load() a library writer. The
        # recovery-rehearsal tests load the LIVE settings by design,
        # read-only by contract, and one suite run migrated a real
        # machine's favourites from inside a test (correctly, but a
        # test must never write live data - test_file_section pins the
        # boundary). Both migrations run from the product surfaces
        # instead: `_ready`'s per-session retry for the locations, the
        # favourite doors for the stars - the sites that already
        # existed because `dir` can be set long after settings load.
        if self._directory and os.path.exists(self._directory):
            return True
        return False
            # return self.get_dir_from_user(True)

