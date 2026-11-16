"""The 2.0 conversion and Check Library rehearsed on a private copy of the real library."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import guard, library_conversion, library_files, material, repair  # noqa: E402
from amaze.tests import test_support                      # noqa: E402


def _sizes(directory: str) -> dict:
    """{relative path: size} of every file under `directory`, the library's trash left out."""
    found = {}
    for here, dirs, names in os.walk(directory):
        if os.path.relpath(here, directory) == ".":
            dirs[:] = [one for one in dirs if one != library_files.TRASH_FOLDER]
        for name in names:
            path = os.path.join(here, name)
            found[os.path.relpath(path, directory).replace(os.sep, "/")] = os.path.getsize(path)
    return found


def _old(directory: str, name: str) -> dict:
    """An old root file as it was written; {} when it is not there or does not read."""
    try:
        with open(os.path.join(directory, name), encoding="utf-8-sig") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _new(directory: str, name: str) -> dict:
    """A 2.0 database as the guard reads it; {} when it is not there."""
    reading = guard.Guard(directory).read(name)
    return dict(reading.document or {})


def _owner(key: str) -> tuple:
    owner, sep, rest = str(key).partition("|")
    return (owner, rest) if sep and len(owner) == 32 else ("", str(key))


def _words(items) -> list:
    """What a comment says, item by item, its ids and authors aside."""
    return [(item.get("t"), str(item.get("text", "")).strip(), item.get("label"),
             item.get("src")) for item in items or [] if isinstance(item, dict)]


class _Census:
    """What a library holds, read in its own shape: rows, comments, stars, icons, people."""

    def __init__(self, directory: str, old: bool) -> None:
        self.rows, self.comments, self.stars, self.icons = {}, {}, set(), {}
        self.locations, self.users, self.settings = {}, {}, {}
        (self._old if old else self._new)(directory)

    def _old(self, directory: str) -> None:
        for old_name, (name, prefix) in library_conversion.OLD_SECTIONS.items():
            document = _old(directory, old_name)
            rows = {library_conversion._row_id(row, index): row
                    for index, row in enumerate(document.get("assets") or [])
                    if isinstance(row, dict)}
            self.rows[name] = set(rows)
            for asset_id, row in rows.items():
                for field in library_conversion.RETIRED_TEXT_FIELDS:
                    text = row.get(field)
                    if isinstance(text, str) and text.strip():
                        self.comments.setdefault((name, asset_id), []).append(
                            ("text", text.strip(), None, None))
        for key, page in (_old(directory, "notes.json").get("notes") or {}).items():
            prefix, _sep, ident = str(key).partition(":")
            if prefix == "file":
                continue    # a file's key is re-homed on its location: counted, not compared
            items = library_conversion._first_shape(page)
            name = {"material": library_files.MATERIALS, "cop": library_files.NODES,
                    "code": library_files.CODE, "gradient": library_files.COLORS}.get(prefix)
            if name and items:
                said = self.comments.setdefault((name, ident), [])
                said.extend(word for word in _words(items) if word not in said)
        owner_of = {asset_id: name for name, ids in self.rows.items() for asset_id in ids}
        for key, value in (_old(directory, "favourites.json").get("favourites") or {}).items():
            owner, bare = _owner(key)
            if value and owner and bare in owner_of:
                self.stars.add((owner_of[bare], owner, bare))
        for key, spec in (_old(directory, "icons.json").get("icons") or {}).items():
            if isinstance(spec, dict) and spec and spec.get("face") not in ("preview", "capture") \
                    and key in owner_of:
                self.icons[(owner_of[key], key)] = spec
        for key, record in (_old(directory, "locations.json").get("locations") or {}).items():
            owner, _bare = _owner(key)
            if owner and isinstance(record, dict) and record:
                self.locations[owner] = self.locations.get(owner, 0) + 1
        self.users = {uid: record.get("name") for uid, record in
                      (_old(directory, "users.json").get("users") or {}).items()
                      if isinstance(record, dict) and str(record.get("name") or "").strip()}
        self.settings = {key: record.get("value") for key, record in
                         (_old(directory, "prefs.json").get("prefs") or {}).items()
                         if isinstance(record, dict) and "value" in record}

    def _new(self, directory: str) -> None:
        for name in library_files.LISTS:
            document = _new(directory, name)
            self.rows[name] = set(document.get("assets") or {})
            for ident, page in (document.get("comments") or {}).items():
                self.comments[(name, ident)] = _words((page or {}).get("items"))
            for owner, own in (document.get("stars") or {}).items():
                self.stars.update((name, owner, key) for key in own or {})
            for key, spec in (document.get("icons") or {}).items():
                self.icons[(name, key)] = spec
        files = _new(directory, library_files.FILES)
        self.locations = {owner: len(own or {})
                          for owner, own in (files.get("locations") or {}).items()}
        master = _new(directory, library_files.MASTER)
        self.users = {uid: record.get("name") for uid, record in
                      (master.get("users") or {}).items()}
        self.settings = {key: record.get("value") for key, record in
                         (master.get("settings") or {}).items()}


class _ConversionRehearsal:
    """The 2.0 conversion run on a private copy of the real library, then proven."""

    def rehearse(self, directory: str, label: str):
        """Convert `directory`, prove every row and setting came through, print a summary."""
        if not library_conversion.needs_conversion(directory):
            self.skipTest("the real library is already 2.0: nothing to rehearse a conversion on")
        before = _Census(directory, old=True)
        started = time.perf_counter()
        outcome = library_conversion.convert(directory, confirm=lambda: True)
        took = time.perf_counter() - started
        self.assertEqual(library_conversion.DONE, outcome.status,
                         "the conversion did not run: %s" % outcome.why)
        after = _Census(directory, old=False)
        aside = {}
        for one in outcome.set_aside:
            if one.row is not None:
                aside.setdefault(one.section, set()).add(one.asset_id)
        for name in library_files.LISTS:
            with self.subTest(section=name):
                self.assertEqual(before.rows.get(name, set()) - aside.get(name, set()),
                                 after.rows.get(name, set()), "rows changed beyond the set-aside")
        missing = [key for key, words in before.comments.items()
                   if key[1] not in aside.get(key[0], set())
                   and any(word not in after.comments.get(key, []) for word in words)]
        self.assertEqual([], missing[:20], "comments that did not come through whole")
        self.assertEqual({star for star in before.stars if star[2] not in aside.get(star[0], ())},
                         {star for star in after.stars if star[2] in after.rows.get(star[0], ())},
                         "stars changed")
        self.assertEqual({key: spec for key, spec in before.icons.items()
                          if key[1] not in aside.get(key[0], set())},
                         {key: spec for key, spec in after.icons.items()
                          if key[1] in after.rows.get(key[0], ())}, "tile icons changed")
        self.assertEqual(before.locations, after.locations, "locations changed")
        self.assertEqual(before.users, after.users, "users changed")
        self.assertEqual(before.settings, after.settings, "shared settings changed")
        sizes = _sizes(directory)
        old_left = [path for path in sizes if "/" not in path and (
            path in library_conversion.OLD_ROOT_FILES + tuple(library_conversion.OLD_MARKS)
            or any(tail in path for tail in library_conversion.OLD_COPY_TAILS))
            and path not in (library_conversion.OLD_POLICY,) + library_files.DATABASES]
        self.assertEqual([], old_left, "old root files or their copies were left")
        kept_aside = {os.path.normpath(path) for one in outcome.set_aside for path in one.files}
        shaped = [path for path in sizes if library_conversion.old_shape(path)
                  and os.path.normpath(os.path.join(directory, path)) not in kept_aside]
        self.assertEqual([], shaped[:20], "format 3 files left that no one set aside")
        for name in library_files.DATABASES:
            reading = guard.Guard(directory).read(name)
            self.assertIn(reading.verdict, (guard.FINE, guard.FRESH),
                          "%s reads %s after the conversion" % (name, reading.verdict))
        self.assertFalse(library_conversion.needs_conversion(directory))
        again = library_conversion.convert(directory, confirm=lambda: True)
        self.assertEqual(library_conversion.NOTHING, again.status)
        self.assertEqual(sizes, _sizes(directory), "a second conversion changed a file")
        sections = ", ".join("%s %d" % (library_files.section_label(name), len(rows))
                             for name, rows in after.rows.items() if rows)
        sys.stderr.write(
            "\n  Conversion rehearsal (%s): %s in %.1f s\n"
            "    rows per section after: %s\n"
            "    comments %d, stars %d, tile icons %d, users %d, shared settings %d, "
            "locations %d\n"
            "    set aside %d (%s); old files removed %d; second conversion: %s\n"
            % (label, outcome.status, took, sections, len(after.comments), len(after.stars),
               len(after.icons), len(after.users), len(after.settings),
               sum(after.locations.values()), len(outcome.set_aside),
               "; ".join(one.name for one in outcome.set_aside) or "none",
               outcome.counts.get("deleted", 0), again.status))
        return outcome


class TheRealLibraryRehearsalTest(_ConversionRehearsal, unittest.TestCase):
    """The databases and every old root file copied whole, each folder's top level as stand-ins."""

    def setUp(self):
        live = test_support.live_library_to_rehearse_on(self)
        self.live = live
        self.dir = tempfile.mkdtemp(prefix="amaze_repair_real_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in sorted(os.listdir(live.dir)):
            source = os.path.join(live.dir, name)
            if os.path.isfile(source) and (
                    name in library_conversion.OLD_ROOT_FILES + library_files.DATABASES
                    + tuple(library_conversion.OLD_MARKS) or any(
                        name.startswith(one + ".") for one in library_conversion.OLD_ROOT_FILES)):
                shutil.copy2(source, os.path.join(self.dir, name))
        folders = [library_files.SECTION_FOLDERS[section] for section in library_files.LISTS] + [
            library_conversion.OLD_PICTURES, library_conversion.OLD_CAPTURES,
            library_files.FILES_FOLDER, library_conversion.OLD_FOLDER]
        for folder in folders:
            if not os.path.isdir(os.path.join(live.dir, folder)):
                continue    # a section that has saved nothing yet
            os.makedirs(os.path.join(self.dir, folder), exist_ok=True)
            for entry in os.listdir(os.path.join(live.dir, folder)):
                source = os.path.join(live.dir, folder, entry)
                if os.path.isdir(source):
                    continue
                target = os.path.join(self.dir, folder, entry)
                if entry.endswith(material.RECORD_SUFFIX) or entry.endswith(".builder.json") \
                        or entry.endswith(".stamp.json"):
                    shutil.copy2(source, target)    # metadata whole: the conversion reads it
                else:
                    with open(target, "wb") as handle:
                        handle.write(b"x")    # a stand-in a byte long: an empty file is no file
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def test_the_conversion_rehearsed_on_the_copy(self):
        """Every row, comment, star, icon, location, user and shared setting comes through."""
        self.rehearse(self.dir, "databases whole, files as stand-ins")

    def test_the_converted_copy_is_coherent_and_nothing_moves(self):
        """The accept path: Check Library finds nothing unlisted, and moves nothing."""
        outcome = library_conversion.convert(self.dir, confirm=lambda: True)
        if outcome.status == library_conversion.NOTHING:
            self.skipTest("the real library is already 2.0")
        self.assertEqual(library_conversion.DONE, outcome.status, outcome.why)
        findings = repair.survey(self.dir, "img/")
        self.assertTrue(findings["complete"])
        self.assertEqual(0, repair.unaccounted_total(findings),
                         "files no section lists: %r" % {
                             folder: names[:5]
                             for folder, names in findings["unaccounted"].items()})
        self.assertEqual([], repair.move_aside(findings, "unlisted", guard_session=False)["moved"])


class TheRealLibrarysWholeShapeTest(_ConversionRehearsal, unittest.TestCase):
    """Every folder of the real library, its databases and records whole, the rest stand-ins."""

    def setUp(self):
        live = test_support.live_library_to_rehearse_on(self)
        self.dir = tempfile.mkdtemp(prefix="amaze_check_real_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        source_root = os.path.normpath(live.dir)
        self.files = 0
        for folder, dirs, names in os.walk(source_root):
            relative = os.path.relpath(folder, source_root)
            here = os.path.normpath(os.path.join(self.dir, relative))
            os.makedirs(here, exist_ok=True)
            if relative in (library_files.PACKAGE_FOLDER, library_files.TRASH_FOLDER):
                dirs[:] = []    # a permanent store the check never enters
                continue
            for name in names:
                source = os.path.join(folder, name)
                target = os.path.join(here, name)
                if relative == "." or name.endswith((material.RECORD_SUFFIX, ".interface")):
                    shutil.copy2(source, target)    # what the conversion and the survey read
                else:
                    with open(target, "wb") as handle:
                        handle.write(b"x")
                    stat = os.stat(source)
                    os.utime(target, (stat.st_atime, stat.st_mtime))
                self.files += 1
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def test_the_conversion_rehearsed_on_the_whole_shape(self):
        """Every folder and version folder, the databases and root files whole."""
        self.rehearse(self.dir, "whole shape")

    def test_unlisted_files_leftovers_and_unknowns_are_told_apart(self):
        outcome = library_conversion.convert(self.dir, confirm=lambda: True)
        self.assertIn(outcome.status, (library_conversion.DONE, library_conversion.NOTHING),
                      outcome.why)
        library_conversion.trash_set_aside(self.dir, outcome.set_aside)    # the end box's Move to Trash
        test_support.reset_database_singletons()
        started = time.perf_counter()
        findings = repair.survey(self.dir, "img/")
        took = time.perf_counter() - started
        sys.stderr.write("\n  Check Library's survey of the real library's shape: "
                         "%.0f ms over %d files\n" % (took * 1000, self.files))
        self.assertTrue(findings["complete"])
        self.assertEqual(0, repair.unaccounted_total(findings),
                         "files no section lists: %r" % {
                             folder: names[:5]
                             for folder, names in findings["unaccounted"].items()})
        leftovers = {entry[0] for entry in findings["leftovers"]}
        unknown = ({entry[0] for entry in findings["unknown"]}
                   | {entry[0] for entry in findings["unknown_folders"]})
        self.assertEqual(set(), leftovers & unknown,
                         "one file was called both a leftover and unknown")
        text = "\n".join(repair.report_lines(findings))
        self.assertNotIn("img/comments", text, "the comment pictures folder is reported")


if __name__ == "__main__":
    unittest.main()
