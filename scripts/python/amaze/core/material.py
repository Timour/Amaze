"""One asset record (Material) and constants shared by the library modules."""

from __future__ import annotations
import os
import re
import uuid
import datetime

from amaze.core import library_files, renderers

REDSHIFT_TERMINALS = ("redshift_material", "redshift_usd_material")

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"    # the stored `date`, seconds always present

CM_TO_SCENE_UNITS = 0.01    # a measured scattering radius is in cm, a scene in metres ▸r/rgl-values


def redshift_terminal(container):
    """The first Redshift terminal of either form among `container`'s children, or None."""
    for child in container.children():
        if child.type().name() in REDSHIFT_TERMINALS:
            return child
    return None


TERMINAL_INPUTS = {
    "surface": ("Surface",),
    "displacement": ("Displacement",),
    "bump": ("Bump Map", "BumpMap"),
}


def terminal_input(named_inputs: dict, role: str):
    """The node wired into a Redshift terminal's `role` input, or None; KeyError on an unknown role."""
    for spelling in TERMINAL_INPUTS[role]:
        wired = named_inputs.get(spelling)
        if wired is not None:
            return wired
    return None


MULTIPLE_VALUES = "Multiple Values..."


_SAFE_ASSET_ID = re.compile(r"[0-9A-Za-z._-]{1,64}\Z")


def is_safe_asset_id(raw) -> bool:
    """True when this id can be used in a filename: no separators, no `.` or `..`."""
    text = str(raw)
    if text in (".", ".."):
        return False
    return bool(_SAFE_ASSET_ID.match(text))


RECORD_SUFFIX = library_files.RECORD_SUFFIX    # `<id>.json`, read and written only by `core/asset_record.py`


def section_folder(library_dir: str, section: str, area: str = "") -> str:
    """`<library>/<section folder>[/<area>]`; KeyError for a database that has no folder."""
    folder = os.path.join(str(library_dir), library_files.SECTION_FOLDERS[section])
    return os.path.join(folder, area) if area else folder


def owned_path(preferences, section: str, area: str, name: str) -> str:
    """`name` in a section's folder or its `area`; `PathOutsideBase` if the path is outside it."""
    from amaze.helpers import hostos
    return hostos.contained_join(section_folder(preferences.dir, section, area), name)


def payload_path(preferences, asset_id, suffix: str, section: str) -> str:
    """`<section folder>/<id><suffix>`; `PathOutsideBase` if the path is outside that folder."""
    return owned_path(preferences, section, "", str(asset_id) + suffix)


def category_names(value) -> list:
    """A record's `categories` as a list of names; a string is one name, its commas included."""
    if not isinstance(value, (list, tuple)):
        value = [value] if isinstance(value, str) else []
    return [name.strip() for name in value if isinstance(name, str) and name.strip()]


class Material:
    """One asset record; keys in `_RETIRED_KEYS` are dropped on load, unknown keys kept."""

    def __init__(
        self,
        name: str = "",
        cats: list[str] | None = None,
        tags: list[str] | None = None,
        fav: bool = False,
        renderer: str = "MatX",
        date: str = "",
        usd: int = 1,
        mat_id: str = "",
    ):

        self._name = name
        self._fav = fav
        self._renderer = renderer
        self.date = date
        self._usd = usd

        # cats and tags go through their setters; a new id is uuid4 hex
        self.categories = cats if cats else ""
        self.tags = tags
        self._mat_id = uuid.uuid4().hex if mat_id == "" else mat_id
        self._cop_net = {}
        self._code = ""
        self._description = ""
        self._about = ""
        self._license = ""
        self._node_color: list = []
        self._extra: dict = {}

    _RETIRED_KEYS = frozenset({"favorite", "icon", "builder"})

    _KNOWN_KEYS = frozenset({
        "id", "name", "categories", "tags", "date",
        "renderer", "usd", "cop_net", "code", "description",
        "about", "license", "node_color",
    }) | _RETIRED_KEYS

    @classmethod
    def from_dict(cls, material_dict: dict) -> Material:
        """A row into a Material, defaults for missing fields, unknown keys kept in `_extra`."""
        name = material_dict.get("name", "")
        cats = material_dict.get("categories", [])
        tags = material_dict.get("tags", [])
        fav = False
        mat_id = material_dict.get("id", "")
        date = material_dict.get("date", "")
        renderer = material_dict.get("renderer", "")
        usd = material_dict.get("usd", False)

        mat = cls(name, cats, tags, fav, renderer, date, usd, mat_id)
        mat.cop_net = material_dict.get("cop_net", {})
        mat.code = material_dict.get("code", "")
        mat.description = material_dict.get("description", "")
        mat.about = material_dict.get("about", "")
        mat.license = material_dict.get("license", "")
        mat.node_color = material_dict.get("node_color", [])
        mat._extra = {
            key: value for key, value in material_dict.items()
            if key not in cls._KNOWN_KEYS
        }
        return mat

    def get_as_dict(self) -> dict:
        """The record as saved - known fields first, then `_extra` last, never overwriting a known key."""
        material_dict = {
            "id": self._mat_id,
            "name": self._name,
            "categories": self._cats,
            "tags": self._tags,
            "date": self._date,
            "renderer": self._renderer,
            "usd": self._usd,
            "cop_net": self._cop_net,
            "code": self._code,
            "description": self._description,
            "about": self._about,
            "license": self._license,
            "node_color": self._node_color,
        }
        for key, value in self._extra.items():
            material_dict.setdefault(key, value)

        return material_dict

    @property
    def cop_net(self) -> dict:
        """COP companion network info ({} if the material has none)"""
        return self._cop_net

    @cop_net.setter
    def cop_net(self, val: dict) -> None:
        self._cop_net = val if val else {}

    @property
    def code(self) -> str:
        """Code section snippet text ('' for other asset types)."""
        return self._code

    @code.setter
    def code(self, val: str) -> None:
        self._code = val or ""

    @property
    def description(self) -> str:
        """Optional human description shown on hover ('' if none)."""
        return self._description

    @description.setter
    def description(self, val: str) -> None:
        self._description = val or ""

    @property
    def about(self) -> str:
        """Credit/about text (author, source, link) - '' if not from an online library."""
        return self._about

    @about.setter
    def about(self, val: str) -> None:
        self._about = val or ""

    @property
    def license(self) -> str:
        """The license the material is released under - '' if unknown."""
        return self._license

    @license.setter
    def license(self, val: str) -> None:
        self._license = val or ""

    @property
    def mat_id(self) -> str:
        """The asset id, as str."""
        return str(self._mat_id)

    @property
    def name(self) -> str:
        """The display name."""
        return self._name

    @name.setter
    def name(self, new_name: str) -> None:
        self._name = new_name

    @property
    def date(self) -> str:
        """The save-time date string; assigning an empty string stores the current time."""
        return self._date

    @date.setter
    def date(self, date: str = "") -> None:
        self._date = date if date != "" else datetime.datetime.now().strftime(
            DATE_FORMAT)

    def set_current_date(self) -> None:
        self.date = ""

    @property
    def fav(self) -> bool:
        """In-memory fallback only; stars are stored per user in the section's database."""
        return self._fav

    @fav.setter
    def fav(self, fav: bool) -> None:
        self._fav = fav

    @property
    def node_color(self) -> list:
        """[r, g, b] the node was colored with at save time, [] for the default grey."""
        return self._node_color

    @node_color.setter
    def node_color(self, val) -> None:
        self._node_color = list(val) if val else []

    @property
    def renderer(self) -> str:
        """The stored renderer, normalized for display and matching."""
        return renderers.normalized(self._renderer)

    @renderer.setter
    def renderer(self, value: str) -> None:
        self._renderer = value

    @property
    def tags(self) -> list[str]:
        """The tag list, `[]` for none; takes a comma string or a list. ▸p/no-tags-is-empty"""
        return self._tags

    @tags.setter
    def tags(self, tags) -> None:
        if isinstance(tags, (list, tuple)):
            found = [str(t).strip() for t in tags if str(t).strip()]
        else:
            found = [t.strip() for t in str(tags or "").split(",")
                     if t.strip()]
        self._tags = found

    @property
    def usd(self) -> int:
        """The stored `usd` flag."""
        return self._usd

    @property
    def categories(self) -> list[str]:
        """The one category as a list of at most one entry; of several, only the first is kept."""
        return self._cats

    @categories.setter
    def categories(self, cats) -> None:
        self._cats = category_names(cats)[:1]

    def remove_category(self, cat: str) -> None:
        if cat in self._cats:
            self._cats.remove(cat)

    def rename_category(self, old: str, new: str) -> None:
        for index, cat in enumerate(self._cats):
            if old == cat:
                self._cats[index] = new

    def set_data(
        self, name: str | None, cats: str, tags: str, fav: bool, renderer: str | None,
        about: str | None = None, license: str | None = None,
    ) -> None:
        """Apply edited fields and stamp the date; `fav` is ignored, None keeps about/license."""
        self.categories = cats
        self.tags = tags
        if renderer:
            self._renderer = renderer
        if name:
            self.name = name
        if about is not None:
            self.about = about
        if license is not None:
            self.license = license
        self.set_current_date()
