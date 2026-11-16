"""One set of source models per library per process; proxies stay per panel. ▸p/one-model-set"""

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
    library_db.library_for(preferences)    # the Prefs every database asks for its user
    library_db.use(preferences)
    found = _models.get(key)
    if found is None:
        found = {attr: cls(preferences) for attr, cls in SOURCE_MODELS}
        _models[key] = found
    else:
        for model in found.values():
            model.preferences = preferences    # the panel that built these may be gone; the live one's Prefs is the one that answers
    return found


def rebind(preferences, model) -> None:
    """File the set holding `model` under `preferences.dir` after a library switch moved it."""
    key = library_db.key_of(preferences)
    library_db.use(preferences)
    for old, models in list(_models.items()):
        if old != key and any(held is model for held in models.values()):
            _models.pop(old)
            _models[key] = models
            library_db._in_use.discard(old)    # the models left it: no longer held
            return


def apply_merged(preferences, name: str, also=None) -> list:
    """Every model of this library on database `name` takes what is held now; the ones that moved."""
    sharing = [] if also is None else [also]
    for model in (_models.get(library_db.key_of(preferences)) or {}).values():
        if getattr(model, "DB_FILENAME", None) == name and not any(
                model is held for held in sharing):
            sharing.append(model)
    sharing.sort(key=lambda model: not isinstance(
        model, QtCore.QAbstractListModel))    # sidebars first: a grid's signal handler can read one
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
    """Read other sessions' saves into every database and model; what moved. ▸r/peer-read"""
    moved = []
    for key, changed in library_db.refresh(preferences).items():
        held = library_db.preferences_of(key)
        models = _models.get(key) or {}
        for name in changed:
            moved.append(name)
            if name == library_files.FILES:
                locations.touch()    # the Files section's keys and records are read afresh
            if held is None:
                continue
            shared = apply_merged(held, name)
            moved.extend(attr for attr, model in models.items()
                         if any(model is one for one in shared))
    return moved


def _after_save(key: str, name: str) -> None:
    """A save merged another session's work in: every model on that database takes it."""
    held = library_db.preferences_of(key)
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
