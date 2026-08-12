"""
Holds Material information
"""

from __future__ import annotations
import os
import re
import uuid
import datetime

#: Redshift's terminal node types, measured 2026-08-09 on 21.0.729 with
#: the plugin loaded: a `redshift_vopnet` ships a `redshift_material`
#: and an `rs_usd_material_builder` a `redshift_usd_material`. Neither
#: names its inputs - they are `Input 1`..`Input 8` - so there is no
#: `surface` connector to look for, and the whole node IS the terminal.
#:
#: HERE rather than in `render/nodes.py`, where it was: the preview
#: engine needs it too and imports only `amaze.core` and
#: `amaze.helpers`, never `amaze.render`. Five sites tested the first
#: literal alone, so every `rs_usd_material_builder` was invisible to
#: them - `nodes` re-exports this name so its own callers are unchanged.
REDSHIFT_TERMINALS = ("redshift_material", "redshift_usd_material")


#: THE MIXED-SELECTION SENTINEL - what an edit field shows when the
#: selected assets disagree, and what set_assetdata reads as the
#: instruction to leave that field alone. It is COMPARED against, so
#: a second spelling anywhere is a silent overwrite waiting; a source
#: scan (test_library.TheSentinelHasOneHome) keeps this the only one.
#: Lives on the asset side because the model cannot import the panel.
MULTIPLE_VALUES = "Multiple Values..."


#: An asset id becomes FILENAMES - `mat/<id>.mat`, `mat/<id>.interface`,
#: `img/<id>.png` - so the only ids that can be honoured are ones that
#: are a single, safe path component.
#:
#: Deliberately NOT "32 hex only", which is what this check was first
#: specified as. New ids are `uuid4().hex`, but the committed test
#: fixture carries six 18-digit legacy timestamp ids and a "-1"
#: sentinel row, and the code promises in Material.__init__ that legacy
#: ids live forever. A 32-hex rule would refuse the whole fixture and
#: every pre-uuid library on disk. What actually has to be excluded is
#: separators and traversal, not an unfamiliar shape.
_SAFE_ASSET_ID = re.compile(r"[0-9A-Za-z._-]{1,64}\Z")


def is_safe_asset_id(raw) -> bool:
    """True when this id can be composed into a filename safely.

    The threat is concrete, not theoretical: `id` is read verbatim out
    of library.json, and with `../../.ssh/authorized_keys` the ordinary
    path composition resolves outside the library entirely - so a
    tampered index picks which file the loader opens. Rejecting the id
    at the boundary is the cheap half; hostos.contained_join is the
    other half, applied where the path is actually built.
    """
    text = str(raw)
    if text in (".", ".."):
        return False
    return bool(_SAFE_ASSET_ID.match(text))


def payload_path(preferences, asset_id, suffix: str) -> str:
    """The absolute path of ONE file asset `asset_id` owns in `mat/`.

    `suffix` is everything after the id - `preferences.ext`,
    `".interface"`, `".builder.json"`, `"_cop" + preferences.ext`.

    THE ONE COMPOSITION. This was written out by hand at twenty sites in
    `render/nodes.py` and `render/thumbs.py` as

        preferences.dir + preferences.asset_dir + str(asset_id) + suffix

    beside `library.asset_files()`'s `contained_join`, and the two agree
    only while `preferences.dir` carries its trailing separator - an
    invariant applied in `Prefs.save()` and nowhere near the twenty
    readers of it. The same split had already been found and closed for
    thumbnails (`tile_icons.thumbnail_path`); this is the payload half
    of it, and `asset_files()` composes through here now so there is one
    answer rather than two that happen to match.

    It also carries the containment check the concatenations did not.
    The id is read verbatim out of library.json, so a tampered index can
    name `../../.ssh/authorized_keys` and choose which file the SAVER
    writes - `is_safe_asset_id` is the door at the record, this is the
    door at the path, and only one of them was on this route.
    """
    from amaze.helpers import hostos
    assets = os.path.join(preferences.dir, preferences.asset_dir)
    return hostos.contained_join(assets, str(asset_id) + suffix)


#: Renderer names that are Karma/MaterialX under the hood.
#:
#: "Karma" is the modern name; "MaterialX" is the legacy stored value
#: from early libraries, and "MtlX" the label online imports briefly
#: carried before they were unified into plain Karma materials. All
#: three are the SAME renderer as far as behaviour goes - capability,
#: import routing, thumbnail dispatch and batch rendering must treat
#: them identically.
#:
#: This exists because adding "MtlX" as a display label silently broke
#: five separate behaviours that each tested for the literal strings
#: "Karma"/"MaterialX": imported materials were refused by the LOP
#: capability check, their import routing matched no branch at all, and
#: rerender/Render All took the wrong path. One predicate so a future
#: renderer label cannot drift the same way.
KARMA_RENDERERS = ("Karma", "MaterialX", "MtlX")


def is_karma_renderer(renderer) -> bool:
    """True for any Karma/MaterialX-family renderer label."""
    name = str(renderer or "")
    return any(known in name for known in KARMA_RENDERERS)


def normalized_renderer(name) -> str:
    """The display/matching name for a STORED renderer string. Early
    libraries stored Karma materials as "MaterialX", and online imports
    were briefly tagged "MtlX" - both ARE Karma materials. Every
    consumer (Material.renderer, the grid's RendererRole, the sidebar
    counts) must map through here or filters and counts drift apart."""
    name = str(name or "")
    return "Karma" if name in ("MaterialX", "MtlX") else name


class Material:
    """
    Holds Material information
    """

    def __init__(
        self,
        name: str = "",
        cats: list[str] | None = None,
        tags: list[str] | None = None,
        fav: bool = False,
        renderer: str = "MatX",
        date: str = "",
        builder: int = 0,
        usd: int = 1,
        mat_id: str = "",
    ):

        self._name = name
        self._fav = fav
        self._renderer = renderer
        self.date = date
        self._builder = builder
        self._usd = usd

        # THROUGH the setter, not around it: from_dict() builds every
        # asset on load this way, so assigning the field directly let a
        # legacy multi-category row survive the one place that exists to
        # collapse it. The rule has to live in one place or it is not a
        # rule.
        self.categories = cats if cats else ""
        self._tags = [""] if not tags else tags
        # uuid4 hex for NEW materials: machine-independent, no
        # timestamp-tick collision window across two Macs. Existing
        # materials keep their legacy timestamp ids forever - scene
        # nodes stamp them as userData and filenames carry them.
        self._mat_id = uuid.uuid4().hex if mat_id == "" else mat_id
        self._cop_net = {}
        # Code section only: the snippet text (VEX/OpenCL/Python).
        # Empty for every other asset type; persisted like any field.
        self._code = ""
        # Optional human description, shown on hover (tooltip). Used by
        # the Code section (curated starter snippets ship with one);
        # empty for anything without a description. Persisted like any
        # field.
        self._description = ""
        # Credit/about text and the license, populated when a material is
        # imported from an online library (author, source, link) to pay
        # homage to the creators. Editable in the Material Info dialog;
        # empty for anything not downloaded. Persisted like any field.
        self._about = ""
        self._license = ""
        # Network-editor node color ([r, g, b]) captured at save time -
        # [] when the node wore the default grey. Restored on import.
        self._node_color: list = []

    #: Keys this build UNDERSTANDS but no longer writes. Named here so
    #: they are recognised and therefore DROPPED: a key `_KNOWN_KEYS`
    #: does not name is carried verbatim by `_extra`, so leaving these
    #: out would put both straight back on the next save and undo the
    #: schema-5 step that strips them. The same shape `_Persistence`
    #: uses for a retired settings key, for the same reason.
    #:
    #: `favorite` is per-user now (`material_favorites` in
    #: settings.json); `icon` lives in `icons.json`, keyed by asset id.
    _RETIRED_KEYS = frozenset({"favorite", "icon"})

    #: Every key this build understands. Anything else on a row is
    #: carried through untouched (see _extra) rather than dropped.
    _KNOWN_KEYS = frozenset({
        "id", "name", "categories", "tags", "date",
        "renderer", "usd", "builder", "cop_net", "code", "description",
        "about", "license", "node_color",
    }) | _RETIRED_KEYS

    @classmethod
    def from_dict(cls, material_dict: dict) -> Material:
        """
        Turns a dict, typically retrieved from the database into a Material Instance

        :param cls: Description
        :param material_dict: Description
        :type material_dict: dict
        :return: Description
        :rtype: Material
        """
        # .get() with defaults, NOT hard indexing. A single missing key
        # used to raise KeyError out of MaterialLibrary.__init__, so the
        # panel could not open AT ALL - verified by deleting "usd" from
        # one row of 546. One damaged row is a damaged row; it must not
        # cost the whole library.
        name = material_dict.get("name", "")
        cats = material_dict.get("categories", [])
        tags = material_dict.get("tags", [])
        # `favorite` is NOT read back: it is per-user now and lives in
        # settings.json, and schema 5 strips it from the row. The
        # in-memory flag stays as the fallback for a preferences object
        # that has no favourites accessor at all.
        fav = False
        mat_id = material_dict.get("id", "")
        date = material_dict.get("date", "")
        renderer = material_dict.get("renderer", "")
        usd = material_dict.get("usd", False)
        builder = material_dict.get("builder", 0)

        mat = cls(name, cats, tags, fav, renderer, date, builder, usd, mat_id)
        mat.cop_net = material_dict.get("cop_net", {})
        mat.code = material_dict.get("code", "")
        mat.description = material_dict.get("description", "")
        mat.about = material_dict.get("about", "")
        mat.license = material_dict.get("license", "")
        mat.node_color = material_dict.get("node_color", [])
        # Everything this build does not recognise, kept verbatim and
        # re-emitted by get_as_dict. Both directions were a FIXED key
        # set, so an older build silently dropped a newer one's fields
        # on the next save - verified: a "future_field" on an asset
        # survived load and was absent after one save(). That is what an
        # older build would do to `icon` across all 546 rows on the
        # other Mac.
        mat._extra = {
            key: value for key, value in material_dict.items()
            if key not in cls._KNOWN_KEYS
        }
        return mat

    def get_as_dict(self) -> dict:
        """
        Return the current Instance as a Dictionary
        Typically used before saving into the DB

        :param self: Description
        :return: Description
        :rtype: dict[Any, Any]
        """
        material_dict = {
            "id": self._mat_id,
            "name": self._name,
            "categories": self._cats,
            "tags": self._tags,
            "date": self._date,
            "renderer": self._renderer,
            "usd": self._usd,
            "builder": self._builder,
            "cop_net": self._cop_net,
            "code": self._code,
            "description": self._description,
            "about": self._about,
            "license": self._license,
            "node_color": self._node_color,
        }
        # Unknown keys last, and they may not overwrite a known one.
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
        """Credit/about text (author, source, link) - '' if not from an
        online library."""
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
        """
        Docstring for mat_id

        :param self: Description
        :return: Description
        :rtype: str
        """
        return str(self._mat_id)

    @property
    def name(self) -> str:
        """
        Docstring for name

        :param self: Description
        :return: Description
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, new_name: str) -> None:
        """
        Docstring for name

        :param self: Description
        :param new_name: Description
        :type new_name: str
        """
        self._name = new_name

    @property
    def date(self) -> str:
        """
        Docstring for date

        :param self: Description
        :return: Description
        :rtype: str
        """
        return self._date

    @date.setter
    def date(self, date: str = "") -> None:
        """
        Docstring for date

        :param self: Description
        :param date: Description
        :type date: str
        """
        self._date = date if date != "" else str(datetime.datetime.now())[:-7]

    def set_current_date(self) -> None:
        """
        Docstring for set_current_date

        :param self: Description
        """
        self.date = ""

    @property
    def fav(self) -> bool:
        """
        Docstring for fav

        :param self: Description
        :return: Description
        :rtype: bool
        """
        return self._fav

    @fav.setter
    def fav(self, fav: bool) -> None:
        """
        Docstring for fav

        :param self: Description
        :param fav: Description
        :type fav: bool
        """
        self._fav = fav

    @property
    def node_color(self) -> list:
        """[r, g, b] the node was colored with at save time, [] for
        the default grey."""
        return self._node_color

    @node_color.setter
    def node_color(self, val) -> None:
        self._node_color = list(val) if val else []

    @property
    def renderer(self) -> str:
        """
        Docstring for renderer

        :param self: Description
        :return: Description
        :rtype: str
        """
        return normalized_renderer(self._renderer)

    @renderer.setter
    def renderer(self, value: str) -> None:
        self._renderer = value

    @property
    def builder(self) -> int:
        """
        Docstring for builder

        :param self: Description
        :return: Description
        :rtype: int
        """
        return self._builder

    @builder.setter
    def builder(self, value) -> None:
        """Whether the saved node WAS a builder. Read-only until now,
        so add_asset could not record it and every newly saved Mantra
        asset carried 0 - which made load_interface_mantra skip the
        saved .interface entirely."""
        self._builder = int(bool(value))

    @property
    def tags(self) -> list[str]:
        """
        Docstring for tags

        :param self: Description
        :return: Description
        :rtype: list[str]
        """
        return self._tags

    @tags.setter
    def tags(self, tags: str) -> None:
        """
        Docstring for tags

        :param self: Description
        :param tags: Description
        :type tags: str
        """
        self._tags = [t.strip() for t in tags.split(",") if t.strip() != ""]

    @property
    def usd(self) -> int:
        """
        Docstring for usd

        :param self: Description
        :return: Description
        :rtype: int
        """
        return self._usd

    @property
    def categories(self) -> list[str]:
        """
        Docstring for categories

        :param self: Description
        :return: Description
        :rtype: list[str]
        """
        return self._cats

    @categories.setter
    def categories(self, cats: str) -> None:
        """An asset has ONE category. Stored as a list purely so the
        database schema is unchanged, but never more than one entry.

        Multi-category was removed deliberately: no interface ever
        offered it (the save dialog is a single combo, "Move to" picks
        one), so it existed only here - and every per-category property
        that came later would have had to invent a rule for which of an
        asset's categories won. Tags are the many-to-many axis.

        Anything with several is collapsed to the FIRST, which is what
        collapse_multicategory() does to legacy rows on load."""
        if isinstance(cats, (list, tuple)):
            found = [str(c).strip() for c in cats if str(c).strip()]
        else:
            found = [c.strip() for c in str(cats).split(",") if c.strip()]
        self._cats = found[:1]

    def remove_category(self, cat: str) -> None:
        """
        Docstring for remove_category

        :param self: Description
        :param cat: Description
        :type cat: str
        """
        if cat in self._cats:
            self._cats.remove(cat)

    def rename_category(self, old: str, new: str) -> None:
        """
        Docstring for rename_category

        :param self: Description
        :param old: Description
        :type old: str
        :param new: Description
        :type new: str
        """
        for index, cat in enumerate(self._cats):
            if old == cat:
                self._cats[index] = new

    def set_data(
        self, name: str | None, cats: str, tags: str, fav: bool, renderer: str | None,
        about: str | None = None, license: str | None = None,
    ) -> None:
        """
        Sets the Material Data to the given parameters

        :param self: Description
        :param name: Description
        :type name: str | None
        :param cats: Description
        :type cats: str
        :param tags: Description
        :type tags: str
        :param fav: Description
        :type fav: bool
        :param renderer: Description
        :type renderer: str | None
        """

        self.categories = cats
        self.tags = tags
        # `fav` is accepted for arity and IGNORED: the record's
        # favourite is frozen history for older builds (overview.md ▸
        # Housekeeping semantics - "this build neither reads nor writes
        # it"). Writing it here made the Edit Info checkbox the one
        # path that still did - and the field is not shared metadata,
        # so it won the merge outright and seeded favourite adoption on
        # machines that had not migrated. The live star is per-user:
        # library.set_assetdata routes it to preferences.
        if renderer:
            self._renderer = renderer
        if name:
            self.name = name
        # None = leave unchanged (the drag/menu recategorise path doesn't
        # touch credits); "" clears, a string sets.
        if about is not None:
            self.about = about
        if license is not None:
            self.license = license
        self.set_current_date()
