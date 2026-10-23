"""The preferences document: the save/load round trip, the path encoding, and the shared keys' trips to the library. ▸p/store-guards"""

import os

from amaze.core import debug, keyed_store, renderers, users
from amaze.helpers import hostos


def _settings_value(value):
    """A settings value as the store sees one: anything json can hold."""
    return value  # returning None is how a normaliser says no, so a stored null reads as an ABSENT key and that key's default wins


SPEC = keyed_store.bind(keyed_store.SETTINGS, _settings_value)  # settings.json is a registered store; only the normaliser lives here

LIBRARY_FIELD = "library"    # in a `users.<uid>` block: the stored spelling of that user's library


def _encode_path(path):
    """Spell a path the way settings.json stores it - one encoder, shared with every other store."""
    if not isinstance(path, str) or not path:
        return path
    return hostos.storage_path_key(path)


def _decode_path(path):
    """A stored spelling back to this machine's path through `hostos.expand_storage_path` - the declared inverse of the encoder above - plus the re-home step for a foreign absolute that no longer exists."""
    if not isinstance(path, str) or not path:
        return path
    if path.startswith("$AMAZE") or path.startswith("~"):
        return hostos.expand_storage_path(path)    # ONE grammar with every other reader (locations.py decodes the same spellings) - two expansions disagreeing at the edges made one stored value resolve to two strings
    clean = path.replace("\\", "/")
    rehomed = hostos.rehome(clean)  # asks the disk only for a path under some home folder
    if rehomed != clean and not os.path.exists(clean):
        debug.event("prefs", "path re-homed from another machine",
                    stored=path, resolved=rehomed)
        return rehomed
    return path


def _decode_paths(paths):
    """Decode a list of stored paths: a non-list answers [] and non-strings are dropped, because load() may not raise."""
    if not isinstance(paths, (list, tuple)):
        return []
    return [_decode_path(p) for p in paths if isinstance(p, str)]


def _decode_records(records) -> dict:
    """Decode a stored records copy's keys: a non-dict answers {}, and a non-dict record is dropped."""
    if not isinstance(records, dict):
        return {}
    return {_decode_path(key): dict(value) for key, value in records.items()
            if isinstance(key, str) and isinstance(value, dict)}


def _encode_paths(paths):
    return [_encode_path(p) for p in paths]


def _listed_libraries(stored) -> list:
    """The stored Library list as folders, each once and in its order; junk reads as an empty list."""
    out, seen = [], set()
    for folder in _decode_paths(stored):
        folder = _normalised_dir(folder)
        same = hostos.comparable_path(folder) if folder else ""
        if same and same not in seen:
            seen.add(same)
            out.append(folder)
    return out


def _normalised_dir(path) -> str:
    """Forward slashes and one trailing slash. Empty stays empty: "/" would be the filesystem root."""
    out = str(path or "").replace("\\", "/")
    if out and not out.endswith("/"):
        out += "/"
    return out


def _default_sections() -> list:
    """Every registered section key, in tab order, derived from the panel's own registry."""
    try:
        from amaze.panel import sections
        return [key for key, _label in sections.all_sections()]
    except Exception:                                    # noqa: BLE001
        return ["material", "gradient", "cop", "code", "file"]  # prefs must load even when the panel package cannot import


def _through_setter(target, name, value, default):
    """Assign `value` through `name`'s validating setter, falling back to `default` when the setter rejects it."""
    try:
        setattr(target, name, value)
    except (TypeError, ValueError):
        debug.event("prefs", "unreadable %s - using the default" % name,
                    value=repr(value))
        setattr(target, name, default)


RENDERER_DEFAULTS = {"_" + r.switch: True for r in renderers.ALL}  # every renderer offered at first

RENDERER_KEYS = {"_" + r.switch: r.switch_stored for r in renderers.ALL}  # data on disk, never tidied

IMG_SUBDIR = "img/"  # the two folders a library needs ▸p/library-creation-doors
ASSET_SUBDIR = "mat/"

SHARED_KEYS = {  # truth in the library's prefs.json: stored key -> (property or None, attr, default)
    "extension": (None, "_ext", ".mat"),
    "img_extension": (None, "_img_ext", ".png"),
    "img_dir": (None, "_img_dir", IMG_SUBDIR),
    "asset_dir": (None, "_asset_dir", ASSET_SUBDIR),
    "rendersize": ("rendersize", "_rendersize", 256),
    "render_on_import": ("render_on_import", "_render_on_import", 1),
    "matx_resolution": ("matx_resolution", "_matx_resolution", "2k"),
    "ram_cache_mb": ("ram_cache_mb", "_ram_cache_mb", 256),
    "matx_parallel_downloads":
        ("matx_parallel_downloads", "_matx_parallel_downloads", 8),
    "texture_parallel_conversions":
        ("texture_parallel_conversions",
         "_texture_parallel_conversions", 4),
    "geometry_shading_mode":
        ("geometry_shading_mode", "_geometry_shading_mode",
         "hiddenlineghost"),
    "geometry_bg": ("geometry_bg", "_geometry_bg", "black"),
    "path_style": ("path_style", "_path_style", "home"),
}
SHARED_KEYS.update({  # every walker and __init__ read this one table ▸p/prefs-defaults
    stored: (attr[1:], attr, RENDERER_DEFAULTS[attr])
    for attr, stored in RENDERER_KEYS.items()})
SHARED_KEYS.update({r.samples: (r.samples, "_" + r.samples, r.samples_default)
                    for r in renderers.ALL})

_INTRODUCED_SECTIONS = ("file",)  # sections younger than settings: absent from a saved list without its seen flag means the list predates the section, not a deliberate OFF

USER_KEYS = {  # one user's view state on THIS machine, under `users.<uid>`; stored key -> (property, attribute, default), the default being what a user switch resets to
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
    "step_size": ("step_size", "_step_size", True),
    "accent_color": ("accent_color", "_accent_color", "#5d7abd"),
    "icon_line_weight":
        ("icon_line_weight", "_icon_line_weight", "template"),
    "file_show_unknown":
        ("file_show_unknown", "_file_show_unknown", True),
    "debug_mode": ("debug_mode", "_debug_mode", False),
    "addon_betas": ("addon_betas", "_addon_betas", False),
}  # five more per-user keys ride beside every walk of this table, each with a nuance a uniform walk cannot carry

USER_RETIRED = tuple(USER_KEYS) + (  # the per-user spellings that leave the flat document once a user exists to carry them; the three File copies mirror per-user state and ride here too
    "thumbsize", "thumbsize_list", "last_file_folder",
    "section_filters", "enabled_sections",
    "file_folders", "file_favorites", "file_location_records") + tuple(
    "enabled_sections_seen_%s" % s for s in _INTRODUCED_SECTIONS)


class _Persistence:
    """The save/load half of `Prefs`, mixed in - it has no state of its own and nothing outside `Prefs` may use it."""

    def _settings_store(self, reread: bool = False):
        """This machine's settings, through the store - THIS object's own handle, never the shared cache."""
        store = getattr(self, "_settings_handle", None)
        if store is None or store.path != os.path.join(  # the configuration directory is read off this object, so a handle minted against another one is a handle on the wrong file
                str(self.path), keyed_store.SETTINGS):
            store = keyed_store.own_store(SPEC, self)
            self._settings_handle = store
        elif reread:
            store.reread()
        return store

    @property
    def _load_failed(self) -> bool:
        """The store's write latch, derived rather than kept, so a repaired settings.json saves again."""
        try:
            return not self._settings_store().writable
        except (ValueError, AttributeError):
            return False  # a Prefs that cannot say where its configuration lives has no store to ask, so nothing is latched

    def save(self) -> None:
        """Sanitize and save the preferences to disk as json, refusing when the store could not read the existing file."""
        store = self._settings_store()
        if not store.writable:
            debug.event("prefs", "save refused - settings.json could not "
                        "be read this session", path=self.path)
            return  # asked BEFORE the push: an object holding pure defaults must not write them into everyone's `prefs.json` either
        self._push_shared()  # the shared keys go to the LIBRARY first, so the document composed below only ever carries the copy
        self.refresh_data()
        retire = list(self._RETIRED_KEYS)
        if self._library_user:  # the per-user spellings retire only once a user exists to carry them, so a userless session keeps the old flat shape
            retire.extend(USER_RETIRED)
        if store.replace(self.data, retire=retire,
                         settle=self._drop_departed_merged):
            self._absorb_committed(store)

    def _absorb_committed(self, store) -> None:
        """The committed document back into the attributes, because the panel paints from those and not from the bytes."""
        self.data = store.everyones()
        stored = self.data.get("users")
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        block = (self._users_blocks.get(self._library_user, {})  # the three File copies sit inside the block once somebody is picked and flat while nobody is, and both shapes are live
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
            self._file_location_records = _decode_records(records)
        if isinstance(self.data.get("libraries"), list):    # another pane's list, when only it moved
            self._libraries = _listed_libraries(self.data["libraries"])

    _RETIRED_KEYS = (  # keys this build deliberately removed, said out loud because the store's unknown-key courtesy would otherwise re-adopt them off disk on every save
        "star_color_mode", "star_custom_color",
        "texture_folders", "texture_favorites", "last_texture_folder",
        "texture_include_subfolders",
        "geometry_folders", "geometry_favorites", "last_geometry_folder",
        "geometry_include_subfolders",
        "hip_folders", "hip_favorites", "last_hip_folder",
        "hip_include_subfolders",
        "file_section_migrated",
        "version_author",  # load() adopts the value into `library_user` first, so naming it here drops the key without dropping the name
    )

    _RETIRED_KEYS = _RETIRED_KEYS + tuple(SHARED_KEYS) + (  # the shared spellings retire with their values safe: the same save writes the `shared_settings` copy and pushes to the library
        "file_folder_names", "file_folder_colors",
        "file_folder_show_all", "file_recursive_folders",
        "file_include_subfolders")

    def _adopt_shared(self) -> None:
        """Fold the library's shared settings over the attributes, through the same setters load() uses."""
        directory = self.dir  # every setter that moves `dir` adopts, so save unsaved edits before moving it
        if not directory or not os.path.isdir(directory):
            return
        from amaze.core import library_prefs
        values = library_prefs.all_values(self)
        if not values:
            return          # fresh, latched or empty - the copy holds
        for stored, (prop, attr, _default) in SHARED_KEYS.items():
            if stored not in values:
                continue
            value = values[stored]
            if prop is None:
                if isinstance(value, str):  # the layout quartet is read-only properties over strings the connector composes paths from, so only a string may land
                    setattr(self, attr, value)
            else:
                _through_setter(self, prop, value,
                                getattr(self, attr, None))

    def _push_shared(self) -> None:
        """Carry the attributes into the library's store in ONE write; a refused or skipped push loses nothing."""
        directory = self.dir
        if not directory or not os.path.isdir(directory):
            return  # with no library directory the store would write a relative path into the CWD, and a latched store must keep its evidence
        from amaze.core import library_prefs
        if not library_prefs.takes_writes(self):
            return
        library_prefs.set_values(self, {
            stored: getattr(self, attr)
            for stored, (_prop, attr, _default) in SHARED_KEYS.items()})

    def _user_state_document(self) -> dict:
        """The current per-user state as its stored keys - ONE composer for the block branch, the flat branch and the switch snapshot."""
        out = {stored: getattr(self, attr)
               for stored, (_prop, attr, _default) in USER_KEYS.items()}
        out["thumbsize"] = self._thumbsize
        out["thumbsize_list"] = self._thumbsize_list
        out["last_file_folder"] = _encode_path(self._last_file_folder)
        out["section_filters"] = dict(self._section_filters)
        out["enabled_sections"] = list(self._enabled_sections)
        out.update(self._sections_seen)
        out["file_folders"] = _encode_paths(self._file_folders)  # the last-known copies, written from the private fields: the public accessors read the library and would re-enter locations.py mid-save
        out["file_favorites"] = _encode_paths(self._file_favorites)
        out["file_location_records"] = {
            _encode_path(k): dict(v)
            for k, v in self._file_location_records.items()}
        return out

    def _apply_user_block(self, block: dict, data: dict) -> None:
        """The per-user reads, one body for load() and the user switch: block first, flat as the migration-source fallback, the default last."""
        def stored_value(key, default):
            return block.get(key, data.get(key, default))

        for stored, (prop, _attr, default) in USER_KEYS.items():
            _through_setter(self, prop, stored_value(stored, default),
                            default)
        try:  # the 64-512 clamp holds on every apply: an older build on the other machine may write a size under the risen grid floor
            self._thumbsize = max(64, min(512, int(
                stored_value("thumbsize", 128) or 128)))
        except (TypeError, ValueError):
            self._thumbsize = 128
        _through_setter(self, "thumbsize_list",  # the list size defaults to the grid size until adjusted
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
            self._section_filters = {}  # settings written before the filter menu served every section: the one remembered renderer becomes Materials' filter, read and never written
            previous = data.get("last_renderer", "")
            if previous:
                self._section_filters["material"] = str(previous)
        self._file_folders = _decode_paths(
            stored_value("file_folders", []))
        self._file_favorites = _decode_paths(
            stored_value("file_favorites", []))
        self._file_location_records = _decode_records(    # the copy served while the library is out of reach
            stored_value("file_location_records", None))
        stored = stored_value("enabled_sections", None)
        self._enabled_sections = (  # a list, or the default: `None`, a str, an int and a dict each used to raise out of load() and kill the panel outright
            [s for s in stored if isinstance(s, str)]
            if isinstance(stored, (list, tuple)) else _default_sections())
        self._sections_seen = {}
        for introduced in _INTRODUCED_SECTIONS:  # a section that did not exist when this state was written cannot have been deliberately disabled, so introduce it once; turning it off afterwards sticks
            seen_key = "enabled_sections_seen_%s" % introduced
            if introduced not in self._enabled_sections and \
                    not stored_value(seen_key, False):
                self._enabled_sections.append(introduced)
            self._sections_seen[seen_key] = True

    def _switch_user_state(self, old: str, new: str) -> None:
        """Change WHOSE view state the attributes describe: snapshot the old user's block, then apply the new one's."""
        if old:  # the invariant every walk of USER_KEYS leans on: the flat attributes always describe the CURRENT user
            block = dict(self._users_blocks.get(old, {}))
            block.update(self._user_state_document())
            self._users_blocks[old] = block
        if not new:
            return
        block = self._users_blocks.get(new)
        if block is None:
            return  # a user with no block on this machine inherits what is on screen, which is what keeps the arrangement across a first mint
        self._apply_user_block(dict(block), {})

    def forget_user(self, uid) -> None:
        """Drop one deleted user's block and save, clearing the pointer first when it names them."""
        uid = str(uid)
        if self._library_user == uid:
            self.library_user = ""    # the switch files their state under their uid, popped next
        self._users_blocks.pop(uid, None)
        self.save()

    def _departed(self, blocks: dict, roster=None) -> list:
        """The uids in `blocks` the prune drops, logged; `roster` is read here only when one could go."""
        library = _encode_path(str(self.dir or ""))
        if not library:
            return []
        mine = keyed_store.path_identity(library)
        candidates = [
            uid for uid, block in blocks.items()
            if uid != self._library_user and isinstance(block, dict)
            and isinstance(block.get(LIBRARY_FIELD), str)
            and block[LIBRARY_FIELD]
            and keyed_store.path_identity(block[LIBRARY_FIELD]) == mine]
        if candidates and roster is None:
            roster = users.roster(self)
        if not roster:
            return []    # unread, unreadable or empty: never a roster to prune against
        doomed = [uid for uid in candidates if uid not in roster]
        for uid in doomed:
            debug.event("prefs", "a user the library no longer lists "
                        "- their view state dropped", uid=uid)
        return doomed

    def _settle_user_blocks(self) -> None:
        """Mark the open library's blocks and drop those whose user its read roster no longer lists."""
        library = _encode_path(str(self.dir or ""))
        roster = users.roster(self) if library else set()
        for uid in roster.intersection(self._users_blocks):
            block = self._users_blocks[uid]
            if block.get(LIBRARY_FIELD) != library:
                self._users_blocks[uid] = dict(
                    block, **{LIBRARY_FIELD: library})
        for uid in self._departed(self._users_blocks, roster):
            del self._users_blocks[uid]

    def _drop_departed_merged(self, document: dict) -> None:
        """The same prune over blocks a save's merge took in from disk, because a merge only adds."""
        blocks = document.get("users")
        if not isinstance(blocks, dict):
            return
        merged = {uid: block for uid, block in blocks.items()
                  if uid not in self._users_blocks}
        doomed = self._departed(merged) if merged else []
        if doomed:
            document["users"] = {uid: block for uid, block in blocks.items()
                                 if uid not in doomed}

    def refresh_data(self) -> dict:
        """Rebuild self.data as the EXACT dict save() serializes, and return it - one producer, which the debug session snapshot also records."""
        self._directory = _normalised_dir(self._directory)
        self.data["directory"] = _encode_path(self._directory)
        self.data["libraries"] = _encode_paths(self.libraries)
        self.data["shared_settings"] = {  # the last-known COPY, one dict under one key, serving the next session when the library is unreachable; the truth goes through `_push_shared`
            stored: getattr(self, attr)
            for stored, (_prop, attr, _default) in SHARED_KEYS.items()}
        self.data["library_user"] = self._library_user
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        self.data["test_mode"] = self._test_mode
        self.data["test_dir"] = _encode_path(self._test_dir)
        if self._library_user:  # the per-user state lands in the user's block over what it already carried, so a newer build's block keys survive; flat while nobody is picked
            block = dict(self._users_blocks.get(self._library_user, {}))
            block.update(self._user_state_document())
            self._users_blocks[self._library_user] = block
        else:
            self.data.update(self._user_state_document())
        self._settle_user_blocks()
        self.data["users"] = {
            uid: dict(block) for uid, block in self._users_blocks.items()}
        return self.data

    def load(self) -> bool:
        """Load the preferences from disk as json, answering False when there is nothing usable - and NEVER raising, because panel._build re-raises."""
        store = self._settings_store(reread=True)  # re-read on purpose: panel.py calls this again when Preferences closes and on a library switch, and the job is to answer with what is on DISK
        if store.state == keyed_store.FRESH:
            debug.event("prefs", "no settings.json yet - opening "
                        "unconfigured", path=self.path)
            return False  # absent is not broken, and this fires on a fresh install; a latch here would mean the library the user then picks is never persisted
        if not store.writable:
            debug.event("prefs", "settings unreadable - opening without a "
                        "library", path=self.path, trace=store.trace)
            return False  # the store has kept the `.unreadable` copy and told the user; refusing to write for the session is the other half
        data = store.everyones()
        self.data = dict(data)  # a copy, not the parse result: refresh_data() mutates this and it must not stay aliased into the store's document
        shared = data.get("shared_settings")  # every shared read below takes the copy first and the flat spelling second, that flat one being the migration source the next save pops
        if not isinstance(shared, dict):
            shared = {}
        self._library_user = str(data.get("library_user", "") or "").strip()  # WHO, before any per-user read: the identity picks which `users.<uid>` block they load from
        if not self._library_user:
            self._library_user = str(  # adopted from the retired `version_author`, so an install that has been signing versions keeps that name and its stems still match (▸p/identity-is-chosen)
                data.get("version_author", "") or "").strip()
        stored = data.get("users")  # per-UID blocks of this machine's per-user keys; a junk shape is dropped rather than raised, and dies on the next save
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        self._apply_user_block(
            self._users_blocks.get(self._library_user, {}), data)
        self._directory = _decode_path(data.get("directory", ""))
        for stored, (prop, attr, default) in SHARED_KEYS.items():
            value = shared.get(stored, data.get(stored, default))
            if prop is None:    # the folder layout: paths are built from it, so only a string lands
                setattr(self, attr,
                        value if isinstance(value, str) else default)
            else:
                _through_setter(self, prop, value, default)
        self._cache_dir = _decode_path(data.get("cache_dir", ""))
        self._test_mode = bool(data.get("test_mode", False))
        self._test_dir = _decode_path(data.get("test_dir", ""))
        self._libraries = _listed_libraries(data.get("libraries"))

        if not isinstance(self._directory, str):  # _decode_path passes a non-str straight through, and `null`, `{}` or `[]` then reach os.path.exists
            self._directory = ""
        self._directory = _normalised_dir(self._directory)    # a folder saved without its slash glues onto file names
        self._settle_user_blocks()
        self._adopt_shared()  # a pure READ: no migration runs here, so no caller of load() writes the library - the product surfaces run those instead
        library = self.dir  # the overlay-aware property, never the raw field: with Test Mode on they name different folders, and on a fresh machine the raw one is empty
        if library and os.path.exists(library):
            return True
        return False
