"""The preferences document: save/load, path encoding, shared keys to the library. ▸p/store-guards"""

import os

from amaze.core import debug, locations, renderers, section_list, users
from amaze.helpers import hostos
from amaze.prefs import settings_store

LIBRARY_FIELD = "library"    # in a `users.<uid>` block: the stored form of that user's library path


def _encode_path(path):
    """Encode a path as settings.json stores it, with the encoder every other store uses."""
    if not isinstance(path, str) or not path:
        return path
    return hostos.storage_path_key(path)


def _decode_path(path):
    """A stored path decoded for this machine; a missing foreign absolute is rebased onto home."""
    if not isinstance(path, str) or not path:
        return path
    if path.startswith("$AMAZE") or path.startswith("~"):
        return hostos.expand_storage_path(path)    # the same decoding every reader uses
    clean = path.replace("\\", "/")
    rehomed = hostos.rehome(clean)  # checks the disk only for a path under a home folder
    if rehomed != clean and not os.path.exists(clean):
        debug.event("prefs", "path re-homed from another machine",
                    stored=path, resolved=rehomed)
        return rehomed
    return path


def _decode_paths(paths):
    """Decode a list of stored paths: a non-list gives [] and non-strings are dropped."""
    if not isinstance(paths, (list, tuple)):
        return []
    return [_decode_path(p) for p in paths if isinstance(p, str)]


def _decode_records(records) -> dict:
    """Decode a stored records copy's keys: a non-dict gives {}; a non-dict record is dropped."""
    if not isinstance(records, dict):
        return {}
    return {_decode_path(key): dict(value) for key, value in records.items()
            if isinstance(key, str) and isinstance(value, dict)}


def _encode_paths(paths):
    return [_encode_path(p) for p in paths]


def _listed_libraries(stored) -> list:
    """The stored Library list as folders, each once and in its order; a non-list gives []."""
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
    """Every section key, in tab order, from section_list."""
    return section_list.keys()


def _through_setter(target, name, value, default):
    """Assign `value` through `name`'s validating setter, or `default` when the setter rejects it."""
    try:
        setattr(target, name, value)
    except (TypeError, ValueError):
        debug.event("prefs", "unreadable %s - using the default" % name,
                    value=repr(value))
        setattr(target, name, default)


RENDERER_DEFAULTS = {"_" + r.switch: True for r in renderers.ALL}  # every renderer offered at first

RENDERER_KEYS = {"_" + r.switch: r.switch_stored for r in renderers.ALL}  # keys in files on disk: never rename them

IMG_SUBDIR = "img/"  # with each asset section's folder, what a library needs ▸p/library-creation

_NEVER_SYNCED = object()  # a shared key this session never read from nor wrote to the library: the next push writes it

POINTERS = (  # settings.json's own scalars as (stored key, setter, decode)
    ("library_user", "library_user", lambda value: str(value or "")),
    ("cache_dir", "cache_dir", _decode_path),
    ("directory", "dir", lambda value: _normalised_dir(_decode_path(value))),
)

SHARED_KEYS = {  # stored in the library's shared settings: stored key -> (property or None, attr, default)
    "extension": (None, "_ext", ".mat"),
    "img_extension": (None, "_img_ext", ".png"),
    "img_dir": (None, "_img_dir", IMG_SUBDIR),
    "rendersize": ("rendersize", "_rendersize", 256),
    "render_on_import": ("render_on_import", "_render_on_import", 1),
    "matx_resolution": ("matx_resolution", "_matx_resolution", "2k"),
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
SHARED_KEYS.update({  # every loop over the keys and __init__ read this table ▸p/prefs-defaults
    stored: (attr[1:], attr, RENDERER_DEFAULTS[attr])
    for attr, stored in RENDERER_KEYS.items()})
SHARED_KEYS.update({r.samples: (r.samples, "_" + r.samples, r.samples_default)
                    for r in renderers.ALL})

USER_KEYS = {  # per-user view state under `users.<uid>`: stored key -> (property, attribute, default)
    "view_mode": ("view_mode", "_view_mode", "grid"),
    "sidebar_width": ("sidebar_width", "_sidebar_width", 0),
    "notes_panel_width":
        ("notes_panel_width", "_notes_panel_width", 0),
    "show_notes": ("show_notes", "_show_notes", False),
    "show_info": ("show_info", "_show_info", False),
    "info_preview": ("info_preview", "_info_preview", True),
    "info_preview_height": ("info_preview_height", "_info_preview_height", 0),
    "show_categories": ("show_categories", "_show_categories", True),
    "sidebar_counts": ("sidebar_counts", "_sidebar_counts", True),
    "show_tooltips": ("show_tooltips", "_show_tooltips", True),
    "render_rat_files": ("render_rat_files", "_render_rat_files", False),
    "system_file_icons": ("system_file_icons", "_system_file_icons", True),
    "hide_empty_categories":
        ("hide_empty_categories", "_hide_empty_categories", True),
    "step_size": ("step_size", "_step_size", True),
    "accent_color": ("accent_color", "_accent_color", "#5d7abd"),
    "icon_line_weight":
        ("icon_line_weight", "_icon_line_weight", "template"),
    "debug_mode": ("debug_mode", "_debug_mode", False),
    "addon_betas": ("addon_betas", "_addon_betas", False),
}  # five more per-user keys are handled separately beside every loop over this table


class _Persistence:
    """The save and load methods of `Prefs`, as a mixin without state, used only by `Prefs`."""

    def _settings_store(self, reread: bool = False):
        """This machine's settings, through the store - THIS object's own handle, never the shared cache."""
        store = getattr(self, "_settings_handle", None)
        path = str(getattr(self, "path", "") or "")
        if not path:
            raise ValueError("this Prefs cannot say where its configuration lives")
        if store is None or store.path != os.path.join(  # a handle made for another configuration directory is replaced
                path, settings_store.FILENAME):
            store = settings_store.SettingsFile(os.path.join(path, settings_store.FILENAME))
            self._settings_handle = store
        elif reread:
            store.reread()
        return store

    @property
    def _load_failed(self) -> bool:
        """True while the store is unwritable; computed, so a repaired settings.json saves again."""
        try:
            return not self._settings_store().writable
        except (ValueError, AttributeError):
            return False  # a Prefs without a configuration path has no store, so it never counts as failed

    def save(self) -> None:
        """Sanitize and save the preferences as json; skipped if the store could not read it."""
        store = self._settings_store()
        if not store.writable:
            debug.event("prefs", "save refused - settings.json could not "
                        "be read this session", path=self.path)
            return  # checked before _write_shared_settings, so unloaded defaults are never written to the library
        self._write_shared_settings()  # the shared keys are written to the LIBRARY first; the document built below holds a copy
        self.refresh_data()
        composed = self.data    # the commit may merge another pane's values over it
        if store.replace(composed, before_write=self._drop_removed_users_from_merge):
            self._apply_saved_document(store, composed)
            store.compare_with(self.refresh_data(follow_library=False))    # its changes are counted from here

    def _apply_saved_document(self, store, composed=None) -> None:
        """Copy the committed document back into the attributes the panel draws from."""
        self.data = store.whole_document()
        stored = self.data.get("users")
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        block = self._users_blocks.get(self._library_user, {})
        folders = block.get("file_folders")
        if isinstance(folders, list):
            self._file_folders = _decode_paths(folders)
        favourites = block.get("file_favorites")
        if isinstance(favourites, list):
            self._file_favorites = _decode_paths(favourites)
        records = block.get("file_location_records")
        if isinstance(records, dict):
            self._file_location_records = _decode_records(records)
        if isinstance(self.data.get("libraries"), list):    # another pane's list, when only that pane changed it
            self._libraries = _listed_libraries(self.data["libraries"])
        if composed is None:
            return
        for key, setter, decode in POINTERS:
            if key in self.data and self.data[key] != composed.get(key):    # the merge kept the other pane's value
                setattr(self, setter, decode(self.data[key]))

    def _apply_shared_settings(self, unchanged_only: bool = False) -> None:
        """Apply the library's shared settings to attributes; `unchanged_only`: keys unchanged here."""
        if not unchanged_only or not hasattr(self, "_shared_seen"):
            self._shared_seen = {}    # a load or another library: nothing written there yet
        directory = self.dir  # every setter that changes `dir` calls this, so save unsaved edits before changing it
        if not directory or not os.path.isdir(directory):
            return
        from amaze.core import library_settings
        values = library_settings.all_values(self)    # fresh, unreadable or empty: a key not in it keeps the local copy
        seen = self._shared_seen
        for stored, (prop, attr, _default) in SHARED_KEYS.items():
            if stored not in values:
                continue
            if unchanged_only and getattr(self, attr) != seen.get(stored, _NEVER_SYNCED):
                continue    # changed here since last read or written: the next push writes it
            value = values[stored]
            if prop is None:
                if isinstance(value, str):  # the three layout keys take strings only
                    setattr(self, attr, value)
            else:
                _through_setter(self, prop, value,
                                getattr(self, attr, None))
            seen[stored] = getattr(self, attr)

    def apply_shared_changes(self) -> None:
        """After a library store re-read: apply other sessions' changes to keys unchanged here."""
        self._apply_shared_settings(unchanged_only=True)

    def _write_shared_settings(self) -> None:
        """Write the shared keys THIS session changed to the library's store in ONE write."""
        directory = self.dir
        if not directory or not os.path.isdir(directory):
            return  # no library directory: write nothing, never a relative path
        from amaze.core import library_settings
        if not library_settings.takes_writes(self):
            return
        self._apply_shared_settings(unchanged_only=True)    # first read what other sessions wrote, for each key unchanged here
        seen = self._shared_seen
        changed = {stored: getattr(self, attr)
                   for stored, (_prop, attr, _default) in SHARED_KEYS.items()
                   if getattr(self, attr) != seen.get(stored, _NEVER_SYNCED)}
        if changed and library_settings.set_values(self, changed):    # on failure: retried at the next save
            seen.update(changed)
            self._apply_shared_settings(unchanged_only=True)    # the commit may have merged in another session's keys

    def _user_state_document(self) -> dict:
        """The current per-user state as its stored keys."""
        out = {stored: getattr(self, attr)
               for stored, (_prop, attr, _default) in USER_KEYS.items()}
        out["thumbsize"] = self._thumbsize
        out["thumbsize_list"] = self._thumbsize_list
        out["last_file_folder"] = _encode_path(self._last_file_folder)
        out["section_filters"] = dict(self._section_filters)
        out["enabled_sections"] = list(self._enabled_sections)
        out["file_folders"] = _encode_paths(self._file_folders)  # from the private fields; the public accessors would re-enter locations.py
        out["file_favorites"] = _encode_paths(self._file_favorites)
        out["file_location_records"] = {
            _encode_path(k): dict(v)
            for k, v in self._file_location_records.items()}
        return out

    def _apply_user_block(self, block: dict) -> None:
        """Apply the per-user state from `block`, a user's own; an empty one gives the defaults."""
        def stored_value(key, default):
            return block.get(key, default)

        for stored, (prop, _attr, default) in USER_KEYS.items():
            _through_setter(self, prop, stored_value(stored, default),
                            default)
        try:  # the 64-512 clamp applies every time
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
        self._section_filters = {
            str(key): str(label) for key, label in stored.items()
        } if isinstance(stored, dict) else {}
        self._file_folders = _decode_paths(
            stored_value("file_folders", []))
        self._file_favorites = _decode_paths(
            stored_value("file_favorites", []))
        self._file_location_records = _decode_records(    # the copy used while the library is unreachable
            stored_value("file_location_records", None))
        stored = stored_value("enabled_sections", None)
        self._enabled_sections = (  # a list, or the default for any other stored type
            [s for s in stored if isinstance(s, str)]
            if isinstance(stored, (list, tuple)) else _default_sections())

    def _switch_user_state(self, old: str, new: str) -> None:
        """Switch the view state to another user: snapshot the old user's block, apply the new one's."""
        if old:  # the flat attributes always describe the current user
            block = dict(self._users_blocks.get(old, {}))
            block.update(self._user_state_document())
            self._users_blocks[old] = block
        if not new:
            return
        block = self._users_blocks.get(new)
        if block is None:
            return  # a user with no block on this machine keeps the current view state
        self._apply_user_block(dict(block))

    def forget_user(self, uid) -> None:
        """Drop one deleted user's block and save, first clearing library_user if it is them."""
        uid = str(uid)
        if self._library_user == uid:
            self.library_user = ""    # the switch stores their state under their uid, removed next
        self._users_blocks.pop(uid, None)
        self.save()

    def _removed_users(self, blocks: dict, roster=None) -> list:
        """The uids in `blocks` to remove, logged; reads `roster` only when a uid is a candidate."""
        library = _encode_path(str(self.dir or ""))
        if not library:
            return []
        mine = locations.path_identity(library)
        candidates = [
            uid for uid, block in blocks.items()
            if uid != self._library_user and isinstance(block, dict)
            and isinstance(block.get(LIBRARY_FIELD), str)
            and block[LIBRARY_FIELD]
            and locations.path_identity(block[LIBRARY_FIELD]) == mine]
        if candidates and roster is None:
            roster = users.roster(self)
        if not roster:
            return []    # unread, unreadable or empty: no roster to compare against
        removed = [uid for uid in candidates if uid not in roster]
        for uid in removed:
            debug.event("prefs", "a user the library no longer lists "
                        "- their view state dropped", uid=uid)
        return removed

    def _update_user_blocks(self) -> None:
        """Record the open library in its users' blocks; drop users the roster no longer lists."""
        library = _encode_path(str(self.dir or ""))
        roster = users.roster(self) if library else set()
        for uid in roster.intersection(self._users_blocks):
            block = self._users_blocks[uid]
            if block.get(LIBRARY_FIELD) != library:
                self._users_blocks[uid] = dict(
                    block, **{LIBRARY_FIELD: library})
        for uid in self._removed_users(self._users_blocks, roster):
            del self._users_blocks[uid]

    def _drop_removed_users_from_merge(self, document: dict) -> None:
        """The same removal for blocks a save's merge added from disk, because a merge only adds."""
        blocks = document.get("users")
        if not isinstance(blocks, dict):
            return
        merged = {uid: block for uid, block in blocks.items()
                  if uid not in self._users_blocks}
        removed = self._removed_users(merged) if merged else []
        if removed:
            document["users"] = {uid: block for uid, block in blocks.items()
                                 if uid not in removed}

    def refresh_data(self, follow_library: bool = True) -> dict:
        """Rebuild self.data as the exact dict save() serializes, and return it; the roster is optional."""
        self._directory = _normalised_dir(self._directory)
        self.data["directory"] = _encode_path(self._directory)
        self.data["libraries"] = _encode_paths(self.libraries)
        self.data["shared_settings"] = {  # the last-known copy, for a session whose library is unreachable
            stored: getattr(self, attr)
            for stored, (_prop, attr, _default) in SHARED_KEYS.items()}
        self.data["library_user"] = self._library_user
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        if self._library_user:  # view state is stored only in a user's block; with no user chosen, only in memory
            block = dict(self._users_blocks.get(self._library_user, {}))
            block.update(self._user_state_document())
            self._users_blocks[self._library_user] = block
        if follow_library:
            self._update_user_blocks()
        self.data["users"] = {
            uid: dict(block) for uid, block in self._users_blocks.items()}
        return self.data

    def load(self) -> bool:
        """Load the preferences from disk; False when nothing is usable, and it never raises."""
        store = self._settings_store(reread=True)  # re-read, so the result matches the disk now
        taken = self._take_document(store)
        if taken or store.state == settings_store.FRESH:    # before the library's values: those are changes
            store.compare_with(self.refresh_data(follow_library=False))
        if not taken:
            return False
        self._update_user_blocks()
        self._apply_shared_settings()  # a pure read: load() never writes the library
        library = self.dir
        return bool(library and os.path.exists(library))

    def _take_document(self, store) -> bool:
        """The attributes set from the store's document; False when it holds nothing usable."""
        if store.state == settings_store.FRESH:
            debug.event("prefs", "no settings.json yet - opening "
                        "unconfigured", path=self.path)
            return False  # a missing file is a fresh install, not a failure: writes stay allowed
        if not store.writable:
            debug.event("prefs", "settings unreadable - opening without a "
                        "library", path=self.path)
            return False  # the store kept the `.unreadable` copy; writes are blocked for the session
        data = store.whole_document()    # in settings_store.LAYOUT, or the store calls it unreadable
        self.data = dict(data)  # a copy: refresh_data() mutates it, and the store's document must not change
        shared = data.get("shared_settings", {})
        self._library_user = data.get("library_user", "").strip()  # the user, before any per-user read: it selects which `users.<uid>` block is loaded
        self._users_blocks = {
            uid: dict(block) for uid, block in data.get("users", {}).items()
            if isinstance(uid, str) and isinstance(block, dict)
        }
        if self._library_user:    # no user chosen: the current view state is the only copy and is kept
            self._apply_user_block(self._users_blocks.get(self._library_user, {}))
        self._directory = _decode_path(data.get("directory", ""))
        for stored, (prop, attr, default) in SHARED_KEYS.items():
            value = shared.get(stored, default)
            if prop is None:    # the folder layout: paths are built from it, so only a string is set
                setattr(self, attr,
                        value if isinstance(value, str) else default)
            else:
                _through_setter(self, prop, value, default)
        self._cache_dir = _decode_path(data.get("cache_dir", ""))
        self._libraries = _listed_libraries(data.get("libraries"))
        self._directory = _normalised_dir(self._directory)    # a folder saved without its slash runs into the file names joined to it
        return True
