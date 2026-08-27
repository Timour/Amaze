"""One asset record (Material) and the family's shared constants."""

from __future__ import annotations
import os
import re
import uuid
import datetime

REDSHIFT_TERMINALS = ("redshift_material", "redshift_usd_material")


def is_surface_shader_type(type_name: str) -> bool:
    """Whether a Redshift node TYPE NAME looks like a surface material - the ONE spelling of the heuristic the converter and the shaderball share, so a renamed default shader is fixed in one place."""
    return "Material" in type_name or "PBR" in type_name


TERMINAL_INPUTS = {
    "surface": ("Surface",),
    "displacement": ("Displacement",),
    "bump": ("Bump Map", "BumpMap"),
}


def terminal_input(named_inputs: dict, role: str):
    """The node wired into a Redshift terminal's `role` input, or None - the two terminal forms spell inputs differently (`Bump Map` vs `BumpMap`), so callers ask by ROLE; KeyError on a role TERMINAL_INPUTS does not name, deliberately."""
    for spelling in TERMINAL_INPUTS[role]:
        wired = named_inputs.get(spelling)
        if wired is not None:
            return wired
    return None


MULTIPLE_VALUES = "Multiple Values..."


_SAFE_ASSET_ID = re.compile(r"[0-9A-Za-z._-]{1,64}\Z")


def is_safe_asset_id(raw) -> bool:
    """True when this id can compose into a filename - ids are read verbatim out of library.json (a traversal there picks which file the loader opens), and legacy 18-digit timestamp ids plus the fixture's "-1" must pass, so the rule bans separators and traversal, never unfamiliar shapes."""
    text = str(raw)
    if text in (".", ".."):
        return False
    return bool(_SAFE_ASSET_ID.match(text))


def payload_path(preferences, asset_id, suffix: str) -> str:
    """THE ONE COMPOSITION of `mat/<id><suffix>` (suffix: `preferences.ext`, ".interface", ".builder.json", "_cop" + ext), with the containment check - `is_safe_asset_id` is the door at the record, this is the door at the path, and every caller shares the trailing-separator invariant through here."""
    from amaze.helpers import hostos
    assets = os.path.join(preferences.dir, preferences.asset_dir)
    return hostos.contained_join(assets, str(asset_id) + suffix)


KARMA_RENDERERS = ("Karma", "MaterialX", "MtlX")


def is_karma_renderer(renderer) -> bool:
    """True for any Karma-family label - Karma, the legacy "MaterialX" and the brief "MtlX" are ONE renderer for capability, routing and thumbnails (overview.md ▸ Renderer terms), and one predicate keeps a new label from splitting them again."""
    name = str(renderer or "")
    return any(known in name for known in KARMA_RENDERERS)


def normalized_renderer(name) -> str:
    """The display/matching name for a STORED renderer string - every consumer must map through here or filters and counts drift apart."""
    name = str(name or "")
    return "Karma" if name in ("MaterialX", "MtlX") else name


class Material:
    """One asset record. `_RETIRED_KEYS` are keys this build understands but no longer writes - named so they are recognised and DROPPED, because an unknown key rides `_extra` verbatim and the next save would put a retired one straight back, undoing the schema step that stripped it. `MULTIPLE_VALUES` is the mixed-selection sentinel, COMPARED against, so it stays the one spelling (test_library.TheSentinelHasOneHome)."""

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

        # cats assigns THROUGH the categories setter - the one place that collapses a legacy multi-category row; new ids are uuid4 hex, legacy timestamp ids live forever (scene nodes and filenames carry them).
        self.categories = cats if cats else ""
        self._tags = [""] if not tags else tags
        self._mat_id = uuid.uuid4().hex if mat_id == "" else mat_id
        self._cop_net = {}
        self._code = ""
        self._description = ""
        self._about = ""
        self._license = ""
        self._node_color: list = []

    _RETIRED_KEYS = frozenset({"favorite", "icon", "builder"})

    _KNOWN_KEYS = frozenset({
        "id", "name", "categories", "tags", "date",
        "renderer", "usd", "cop_net", "code", "description",
        "about", "license", "node_color",
    }) | _RETIRED_KEYS

    @classmethod
    def from_dict(cls, material_dict: dict) -> Material:
        """A row into a Material - .get() with defaults throughout, because one damaged row must not cost the whole library its open; `favorite` is deliberately not read back (per-user now, schema 5 strips it), and everything unrecognised rides `_extra` verbatim so an older build cannot strip a newer one's fields on its next save."""
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
        for key, value in (getattr(self, "_extra", None) or {}).items():
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
        """The save-time date string; assigning "" stamps now."""
        return self._date

    @date.setter
    def date(self, date: str = "") -> None:
        self._date = date if date != "" else str(datetime.datetime.now())[:-7]

    def set_current_date(self) -> None:
        self.date = ""

    @property
    def fav(self) -> bool:
        """In-memory fallback only - the record's favourite field is dead, stars live per-user in favourites.json."""
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
        return normalized_renderer(self._renderer)

    @renderer.setter
    def renderer(self, value: str) -> None:
        self._renderer = value

    @property
    def tags(self) -> list[str]:
        """The tag list; assigning takes a comma-separated string, stripped."""
        return self._tags

    @tags.setter
    def tags(self, tags: str) -> None:
        self._tags = [t.strip() for t in tags.split(",") if t.strip() != ""]

    @property
    def usd(self) -> int:
        """The stored `usd` flag."""
        return self._usd

    @property
    def categories(self) -> list[str]:
        """An asset has ONE category, stored as a ≤1-entry list so the schema is unchanged; several collapse to the FIRST, and tags are the many-to-many axis (overview.md ▸ Models & storage)."""
        return self._cats

    @categories.setter
    def categories(self, cats: str) -> None:
        if isinstance(cats, (list, tuple)):
            found = [str(c).strip() for c in cats if str(c).strip()]
        else:
            found = [c.strip() for c in str(cats).split(",") if c.strip()]
        self._cats = found[:1]

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
        """Apply edited fields and stamp the date. `fav` is accepted for arity and IGNORED - the live star is per-user via preferences, and writing the record field here seeded favourite adoption on unmigrated machines (overview.md ▸ Housekeeping semantics). For about/license, None leaves the field unchanged, "" clears it."""
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
