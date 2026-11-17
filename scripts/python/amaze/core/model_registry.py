"""One set of source models per library per process; proxies are per panel. ▸p/one-model-set"""

from __future__ import annotations

from PySide6 import QtCore

from amaze.core import (category, code_library, cop_library, debug, file_library,
                        gradient_library, library, library_db, library_files, locations)

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


def models_for(preferences) -> dict:
    """`{attribute: model}` for this library - built once, then handed to every panel."""
    key = library_db.key_of(preferences)
    library_db.library_for(preferences)    # stores the Prefs each database reads its user name from
    library_db.use(preferences)
    found = _models.get(key)
    if found is None:
        found = {attr: cls(preferences) for attr, cls in SOURCE_MODELS}
        _models[key] = found
    else:
        for model in found.values():
            model.preferences = preferences    # the panel that built these may be closed; use the caller's Prefs
    return found


def rebind(preferences, model) -> None:
    """Re-key the set holding `model` to `preferences.dir` after a library switch changed the folder."""
    key = library_db.key_of(preferences)
    library_db.use(preferences)
    for old, models in list(_models.items()):
        if old != key and any(held is model for held in models.values()):
            _models.pop(old)
            _models[key] = models
            library_db._in_use.discard(old)    # no model uses the old key any more
            return


def apply_merged(preferences, name: str, also=None) -> list:
    """Run `apply_refresh` on each model of this library on database `name`; return those that changed."""
    sharing = [] if also is None else [also]
    for model in (_models.get(library_db.key_of(preferences)) or {}).values():
        if getattr(model, "DB_FILENAME", None) == name and not any(
                model is held for held in sharing):
            sharing.append(model)
    sharing.sort(key=lambda model: not isinstance(
        model, QtCore.QAbstractListModel))    # sidebar models first: a grid's signal handler may read one
    moved = []
    for model in sharing:
        apply_refresh = getattr(model, "apply_refresh", None)
        if apply_refresh is None:
            continue
        try:
            if apply_refresh():
                moved.append(model)
        except Exception as exc:                             # noqa: BLE001
            debug.event("database", "model refresh failed", model=type(model).__name__,
                        store=name, error=str(exc))
    return moved


def refresh_all(preferences=None) -> list:
    """Read other sessions' saves into every database and model; return what changed. ▸r/peer-read"""
    moved = []
    for key, changed in library_db.refresh(preferences).items():
        held = library_db.preferences_of(key)
        models = _models.get(key) or {}
        for name in changed:
            moved.append(name)
            if name == library_files.FILES:
                locations.touch()    # Files keys and records are recomputed on next use
            if held is None:
                continue
            if name == library_files.FILES:
                locations.fold_duplicate_ids(held)
            shared = apply_merged(held, name)
            moved.extend(attr for attr, model in models.items()
                         if any(model is one for one in shared))
    return moved


def _after_save(key: str, name: str) -> None:
    """After a save merged another session's changes, refresh every model on that database."""
    held = library_db.preferences_of(key)
    if name == library_files.FILES:
        locations.touch()    # as in `refresh_all`: a merge may have changed the location ids
        if held is not None:
            locations.fold_duplicate_ids(held)
    if held is not None and key in _models:
        apply_merged(held, name)


library_db.on_saved(_after_save)


def release(preferences=None) -> None:
    """Drop the cached models and databases - a library switch onto a different tree, or a test."""
    if preferences is None:
        _models.clear()
    else:
        _models.pop(library_db.key_of(preferences), None)
    library_db.release(preferences)
