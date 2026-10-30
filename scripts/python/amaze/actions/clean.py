"""Clean Up Library in one pass, without the panel's questions. ▸archive/actions/clean.py"""

import os

from amaze.core import debug
from amaze.helpers import hostos


def clean_library(preferences, material_model, category_model, cop_model, cop_category_model,
                  file_folders_model) -> list:
    """The Materials and Node passes, then dead folders and favorites; the report's sections."""
    sections = []

    rescued = material_model.cleanup_db()
    if rescued:
        category_model.check_add_category("Uncategorized")
    normalized = category_model.normalize_categories()
    if normalized:
        debug.event("cleanup", "legacy category entries normalized",
                    count=normalized)
    mat_summary = list(
        getattr(material_model, "last_cleanup_summary", [])
    )
    if mat_summary:
        sections.append("Materials:\n- " + "\n- ".join(mat_summary))

    if cop_model:
        cop_rescued = cop_model.cleanup_db()
        if cop_rescued:
            cop_category_model.check_add_category("Uncategorized")
        cop_category_model.normalize_categories()
        cop_summary = list(
            getattr(cop_model, "last_cleanup_summary", [])
        )
        if cop_summary:
            sections.append("Node assets:\n- " + "\n- ".join(cop_summary))

    browser_lines = clean_folders_and_favorites(preferences, file_folders_model)
    if browser_lines:
        sections.append("Folders and favorites:\n- " + "\n- ".join(browser_lines))
    return sections


def clean_folders_and_favorites(preferences, file_folders_model) -> list:
    """A folder not here loses its pointer, a star on a file gone from its folder goes; disk untouched."""
    lines = []

    set_aside = []
    skipped_unmounted = 0
    folders = list(preferences.file_folders)    # the live file_* keys only ▸archive/actions/clean.py
    for index in range(len(folders) - 1, -1, -1):    # highest row first, so removing one never shifts the row of another not yet examined
        path = folders[index]
        if os.path.isdir(path):
            continue
        if hostos.volume_unreachable(path):    # unreachable is not gone: a blinking network share
            skipped_unmounted += 1
            debug.event("cleanup", "folder pointer kept - its volume "
                        "is not mounted", path=path)
            continue
        debug.event("cleanup", "folder pointer set aside", path=path)
        file_folders_model.set_aside_folder(index + 1)    # the pointer only; row 0 is the synthetic "All"
        set_aside.append(path)
    if set_aside:
        lines.append(    # NAMES, not a count - a count is a sentence nobody can check
            "These folders are not on this computer, so they were set aside. "
            "Their comments, icons and favorites are kept, and come back "
            "when the folder is added again:\n  " + "\n  ".join(sorted(set_aside)))
    if skipped_unmounted:
        lines.append(
            "%d folder(s) on an unmounted drive were left alone - "
            "they will be back when the drive is."
            % skipped_unmounted)

    removed_favs = []
    for path, drop in (
            [(p, preferences.remove_file_favorite)
             for p in list(preferences.file_favorites)]):
        if os.path.exists(path):
            continue
        if hostos.volume_unreachable(path):
            debug.event("cleanup", "favorite kept - its volume is "
                        "not mounted", path=path)
            continue
        if not os.path.isdir(os.path.dirname(path)):    # its folder is not here, set aside or unsynced
            debug.event("cleanup", "favorite kept - its folder is not here",
                        path=path)
            continue
        debug.event("cleanup", "missing-file favorite removed",
                    path=path)
        drop(path)
        removed_favs.append(path)
    if removed_favs:
        lines.append(
            "These favorites pointed at files that are gone, so they "
            "were removed:\n  " + "\n  ".join(sorted(removed_favs)))
    return lines
