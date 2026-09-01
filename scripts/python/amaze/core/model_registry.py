"""ONE set of source models per library per process - `models_for(prefs)` answers the same objects for every panel on that library; proxies, selection models and delegates stay PER PANEL and are not built here. ▸p/one-model-set"""

from __future__ import annotations

from amaze.core import (category, code_library, cop_library, file_library,
                        gradient_library, keyed_store, library)
from amaze.helpers import hostos

SOURCE_MODELS = (    # attribute on the panel -> the class that builds it, every one taking `preferences` alone
    ("category_model", category.Categories),
    ("material_model", library.MaterialLibrary),
    ("file_folders_model", file_library.FileFolders),
    ("file_files_model", file_library.FileFiles),
    ("gradient_model", gradient_library.GradientLibrary),
    ("gradient_categories_model", gradient_library.GradientCategories),
    ("cop_model", cop_library.CopLibrary),
    ("cop_category_model", cop_library.CopCategories),
    ("code_model", code_library.CodeLibrary),
    ("code_category_model", code_library.CodeCategories),
)

_models: dict = globals().get("_models", {})    # survives the panel's module reload ▸r/module-reload


def _key(preferences) -> str:
    return hostos.canonical_path_key(str(getattr(preferences, "dir", "") or ""))


def models_for(preferences) -> dict:
    """`{attribute: model}` for this library - built once, then handed to every panel."""
    key = _key(preferences)
    found = _models.get(key)
    if found is None:
        found = {attr: cls(preferences) for attr, cls in SOURCE_MODELS}
        _models[key] = found
    else:
        for model in found.values():
            model.preferences = preferences    # the panel that built these may be gone; the live one's Prefs is the one that answers
    return found


def rebind(preferences, model) -> None:
    """File the set holding `model` under `preferences.dir` after a switch moved it - left under the old key, the next panel opening on this library is built a second set. Identified by the MODEL, never by the Prefs object: the shared models carry whichever panel looked them up last."""
    key = _key(preferences)
    for old, models in list(_models.items()):
        if old != key and any(held is model for held in models.values()):
            _models.pop(old)
            _models[key] = models
            return


def refresh_all() -> list:
    """Take what another machine wrote into every shared model and every open store, and answer what moved. For a DOOR a person opens - a panel becoming visible, a dialog - since each one costs a read. ▸r/peer-read"""
    from amaze.core import database, debug

    moved = []
    for key, models in list(_models.items()):
        preferences = getattr(models.get("material_model"), "preferences",
                              None)
        if preferences is None:
            continue
        for filename in {getattr(m, "DB_FILENAME", None)    # merge each file ONCE, then let every model take its share: the grid and the sidebar share a connector, so a per-model refresh spends it on whichever runs first
                         for m in models.values()} - {None}:
            try:
                db = database.DatabaseConnector(filename)
                if db.serves(preferences.dir):
                    db.refresh()
            except Exception as exc:                         # noqa: BLE001
                debug.event("database", "refresh failed", store=filename,
                            library=key, error=str(exc))
        for attr, model in models.items():
            apply_refresh = getattr(model, "apply_refresh", None)
            if apply_refresh is None:
                continue    # `file_folders_model` and `file_files_model` are deliberately out: they scan real directories, not a library file
            try:
                db = database.DatabaseConnector(model.DB_FILENAME)
                if db.serves(preferences.dir) and apply_refresh(db):    # the connector is one object per FILENAME, so an entry for another library would drain THIS one's adopted rows
                    moved.append(attr)
            except Exception as exc:                         # noqa: BLE001
                debug.event("database", "model refresh failed",
                            model=attr, library=key, error=str(exc))
        moved.extend(keyed_store.refresh_all(preferences))
    return moved


def release(preferences=None) -> None:
    """Drop the cached models - a library switch onto a different tree, or a test."""
    if preferences is None:
        _models.clear()
        return
    _models.pop(_key(preferences), None)
