"""The preferences document: save/load, path encoding, shared keys to the library. ▸p/store-guards"""

import os

from amaze.core import debug, locations, renderers, section_list, users
from amaze.helpers import hostos
from amaze.prefs import settings_store

LIBRARY_FIELD = "library"    # in a `users.<uid>` block: the stored spelling of that user's library


def _encode_path(path):
    """Spell a path the way settings.json stores it - one encoder, shared with every other store."""
    if not isinstance(path, str) or not path:
        return path
    return hostos.storage_path_key(path)


def _decode_path(path):
    """A stored spelling back to this machine's path, re-homing a foreign absolute that is gone."""
    if not isinstance(path, str) or not path:
        return path
    if path.startswith("$AMAZE") or path.startswith("~"):
        return hostos.expand_storage_path(path)    # the one grammar every reader shares
    clean = path.replace("\\", "/")
    rehomed = hostos.rehome(clean)  # asks the disk only for a path under some home folder
    if rehomed != clean and not os.path.exists(clean):
        debug.event("prefs", "path re-homed from another machine",
                    stored=path, resolved=rehomed)
        return rehomed
    return path


def _decode_paths(paths):
    """Decode a list of stored paths: a non-list answers [] and non-strings are dropped."""
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
    """Every section key, in tab order, from the one list."""
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

RENDERER_KEYS = {"_" + r.switch: r.switch_stored for r in renderers.ALL}  # data on disk, never tidied

IMG_SUBDIR = "img/"  # with each asset section's folder, what a library needs ▸p/library-creation-doors

_UNSEEN = object()  # a shared key this session never adopted nor pushed: the next push carries it

POINTERS = (  # settings.json's own scalars as (stored key, setter, decode)
    ("library_user", "library_user", lambda value: str(value or "")),
    ("cache_dir", "cache_dir", _decode_path),
    ("directory", "dir", lambda value: _normalised_dir(_decode_path(value))),
)

SHARED_KEYS = {  # truth in the library's shared settings: stored key -> (property or None, attr, default)
    "extension": (None, "_ext", ".mat"),
    "img_extension": (None, "_img_ext", ".png"),
    "img_dir": (None, "_img_dir", IMG_SUBDIR),
    "rendersize": ("rendersize", "_rendersize", 256),
    "render_on_import": ("render_on_import", "_render_on_import", 1),
    "obj_drag_outline": ("obj_drag_outline", "_obj_drag_outline", 1),
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

USER_KEYS = {  # per-user view state under `users.<uid>`: stored key -> (property, attribute, default)
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
}  # five more per-user keys are handled by hand beside every walk of this table

LAYOUT = {  # settings.json's top-level keys and the type each must have; a wrong one: no settings
    "directory": str, "libraries": list, "shared_settings": dict, "library_user": str,
    "cache_dir": str, "users": dict,
}


def usable(data: dict) -> bool:
    """Whether a settings document is in the one layout: each key of `LAYOUT` it holds, its type."""
    return all(isinstance(data[key], kind) for key, kind in LAYOUT.items() if key in data)


class _Persistence:
    """The save/load half of `Prefs`, mixed in; stateless, and for `Prefs` alone."""

    def _settings_store(self, reread: bool = False):
        """This machine's settings, through the store - THIS object's own handle, never the shared cache."""
        store = getattr(self, "_settings_handle", None)
        path = str(getattr(self, "path", "") or "")
        if not path:
            raise ValueError("this Prefs cannot say where its configuration lives")
        if store is None or store.path != os.path.join(  # a handle minted for another configuration directory is re-minted
                path, settings_store.FILENAME):
            store = settings_store.SettingsFile(os.path.join(path, settings_store.FILENAME))
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
        """Sanitize and save the preferences as json; refuses when the store could not read the file."""
        store = self._settings_store()
        if not store.writable:
            debug.event("prefs", "save refused - settings.json could not "
                        "be read this session", path=self.path)
            return  # asked before the push, so pure defaults never reach the library's settings
        self._push_shared()  # the shared keys go to the LIBRARY first, so the document composed below only ever carries the copy
        self.refresh_data()
        composed = self.data    # the commit may merge another pane's values over it
        if store.replace(composed, settle=self._drop_departed_merged):
            self._absorb_committed(store, composed)

    def _absorb_committed(self, store, composed=None) -> None:
        """The committed document back into the attributes, which the panel paints from."""
        self.data = store.everyones()
        stored = self.data.get("users")
        self._users_blocks = {
            uid: dict(block) for uid, block in stored.items()
            if isinstance(uid, str) and isinstance(block, dict)
        } if isinstance(stored, dict) else {}
        block = (self._users_blocks.get(self._library_user, {})  # the File copies sit in the block once a user is picked, flat until then
                 if self._library_user else self.data)
        folders = block.get("file_folders")
        if isinstance(folders, list):
            self._file_folders = _decode_paths(folders)
        favourites = block.get("file_favorites")
        if isinstance(favourites, list):
            self._file_favorites = _decode_paths(favourites)
        records = block.get("file_location_records")
        if isinstance(records, dict):
            self._file_location_records = _decode_records(records)
        if isinstance(self.data.get("libraries"), list):    # another pane's list, when only it moved
            self._libraries = _listed_libraries(self.data["libraries"])
        if composed is None:
            return
        for key, setter, decode in POINTERS:
            if key in self.data and self.data[key] != composed.get(key):    # the merge took theirs
                setattr(self, setter, decode(self.data[key]))

    def _adopt_shared(self, follow: bool = False) -> None:
        """Fold the library's shared settings over the attributes; `follow`: keys left alone here only."""
        if not follow or not hasattr(self, "_shared_seen"):
            self._shared_seen = {}    # a load or another library: nothing pushed there yet
        directory = self.dir  # every setter that moves `dir` adopts, so save unsaved edits before moving it
        if not directory or not os.path.isdir(directory):
            return
        from amaze.core import library_settings
        values = library_settings.all_values(self)    # fresh, latched or empty: the copy holds
        seen = self._shared_seen
        for stored, (prop, attr, _default) in SHARED_KEYS.items():
            if stored not in values:
                continue
            if follow and getattr(self, attr) != seen.get(stored, _UNSEEN):
                continue    # changed here since adopted or pushed: the next push carries it
            value = values[stored]
            if prop is None:
                if isinstance(value, str):  # the layout quartet takes strings only
                    setattr(self, attr, value)
            else:
                _through_setter(self, prop, value,
                                getattr(self, attr, None))
            seen[stored] = getattr(self, attr)

    def follow_shared(self) -> None:
        """After a door re-read the library's stores: what peers changed, for keys left alone here."""
        self._adopt_shared(follow=True)

    def _push_shared(self) -> None:
        """The shared keys THIS session changed, into the library's store in ONE write."""
        directory = self.dir
        if not directory or not os.path.isdir(directory):
            return  # no library directory: write nothing, never a relative path
        from amaze.core import library_settings
        if not library_settings.takes_writes(self):
            return
        self._adopt_shared(follow=True)    # first what peers wrote, for each key left alone here
        seen = self._shared_seen
        changed = {stored: getattr(self, attr)
                   for stored, (_prop, attr, _default) in SHARED_KEYS.items()
                   if getattr(self, attr) != seen.get(stored, _UNSEEN)}
        if changed and library_settings.set_values(self, changed):    # refused: retried next save
            seen.update(changed)
            self._adopt_shared(follow=True)    # the commit may have merged a peer's keys in

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
        """Apply the per-user state from `block`: the user's own, or the flat document with none picked."""
        def stored_value(key, default):
            return block.get(key, default)

        for stored, (prop, _attr, default) in USER_KEYS.items():
            _through_setter(self, prop, stored_value(stored, default),
                            default)
        try:  # the 64-512 clamp holds on every apply
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
        self._file_location_records = _decode_records(    # the copy served while the library is out of reach
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
            return  # a user with no block on this machine inherits what is on screen
        self._apply_user_block(dict(block))

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
        """Rebuild self.data as the exact dict save() serializes, and return it."""
        self._directory = _normalised_dir(self._directory)
        self.data["directory"] = _encode_path(self._directory)
        self.data["libraries"] = _encode_paths(self.libraries)
        self.data["shared_settings"] = {  # the last-known copy, for a session whose library is unreachable
            stored: getattr(self, attr)
            for stored, (_prop, attr, _default) in SHARED_KEYS.items()}
        self.data["library_user"] = self._library_user
        self.data["cache_dir"] = _encode_path(self._cache_dir)
        if self._library_user:  # into the user's block, keeping keys it already carried; flat while nobody is picked
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
        """Load the preferences from disk; False when nothing is usable, and it never raises."""
        store = self._settings_store(reread=True)  # re-read, so the answer is what is on disk now
        if store.state == settings_store.FRESH:
            debug.event("prefs", "no settings.json yet - opening "
                        "unconfigured", path=self.path)
            return False  # absent is a fresh install, not broken: no latch
        if not store.writable:
            debug.event("prefs", "settings unreadable - opening without a "
                        "library", path=self.path)
            return False  # the store kept the `.unreadable` copy; writes are refused for the session
        data = store.everyones()
        self.data = dict(data)  # a copy: refresh_data() mutates it, and the store's document must not change
        if not usable(data):
            debug.event("prefs", "settings.json is in no layout this Amaze reads - "
                        "opening as on a first run", path=self.path)
            return False  # the defaults stand; a key it does not know stays in the file
        shared = data.get("shared_settings", {})
        self._library_user = data.get("library_user", "").strip()  # WHO, before any per-user read: the identity picks which `users.<uid>` block they load from
        self._users_blocks = {
            uid: dict(block) for uid, block in data.get("users", {}).items()
            if isinstance(uid, str) and isinstance(block, dict)
        }
        self._apply_user_block(
            self._users_blocks.get(self._library_user, {}) if self._library_user else data)
        self._directory = _decode_path(data.get("directory", ""))
        for stored, (prop, attr, default) in SHARED_KEYS.items():
            value = shared.get(stored, default)
            if prop is None:    # the folder layout: paths are built from it, so only a string lands
                setattr(self, attr,
                        value if isinstance(value, str) else default)
            else:
                _through_setter(self, prop, value, default)
        self._cache_dir = _decode_path(data.get("cache_dir", ""))
        self._libraries = _listed_libraries(data.get("libraries"))
        self._directory = _normalised_dir(self._directory)    # a folder saved without its slash glues onto file names
        self._settle_user_blocks()
        self._adopt_shared()  # a pure read: load() never writes the library
        library = self.dir
        if library and os.path.exists(library):
            return True
        return False
