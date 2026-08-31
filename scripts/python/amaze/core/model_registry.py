"""ONE set of source models per library per process - `models_for(prefs)` answers the same objects for every panel on that library; proxies, selection models and delegates stay PER PANEL and are not built here. ▸p/one-model-set"""

from __future__ import annotations

from amaze.core import (category, code_library, cop_library, file_library,
                        gradient_library, library)
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


def rebind(preferences) -> None:
    """File this library's models under `preferences.dir` after a switch moved it - a model left under the old key is served to the next panel that opens there."""
    key = _key(preferences)
    for old, models in list(_models.items()):
        if old != key and any(
                getattr(m, "preferences", None) is preferences
                for m in models.values()):
            _models.pop(old)
            _models[key] = models


def release(preferences=None) -> None:
    """Drop the cached models - a library switch onto a different tree, or a test."""
    if preferences is None:
        _models.clear()
        return
    _models.pop(_key(preferences), None)
