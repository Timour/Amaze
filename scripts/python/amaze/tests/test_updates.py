"""Updates and the library's version: one test per requirement in docs/requirements/updates.md."""

import contextlib
import errno
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import types
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

from amaze import amazetheme, messages  # noqa: E402
from amaze.actions import library as library_actions  # noqa: E402
from amaze.core import (guard, library_db, library_policy, library_settings,  # noqa: E402
                        matx_sources, updater, users)
from amaze.helpers import helpers  # noqa: E402
from amaze.prefs import persistence  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import faults, test_support  # noqa: E402

URL = "https://example.invalid/Amaze-9.9.zip"
ENTRIES = updater.INSTALL_ENTRIES


def release(version="9.9", drop=(), extra=None) -> bytes:
    """A release archive as GitHub serves it: the repo under one folder."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        for entry in ENTRIES:
            if entry not in drop:
                bundle.writestr("Amaze/%s" % (entry if "." in entry else entry + "/a.txt"), version)
        for name, data in (extra or {}).items():
            bundle.writestr(name, data)
    return archive.getvalue()


def full_disk(under: str):
    """`shutil.copytree` that fails as on a full disk for a source in a folder named `under`."""
    real = shutil.copytree

    def copy(source, target, *args, **how):
        if under in source.replace(os.sep, "/").split("/"):
            raise OSError(errno.ENOSPC, "No space left on device", target)
        return real(source, target, *args, **how)
    return copy if under else mock.Mock(side_effect=OSError(errno.ENOSPC, "No space left"))


@contextlib.contextmanager
def esc_during_download(name):
    """`helpers.download_operation` with Esc pressed at the first piece of the download."""
    def on_bytes(read, total):
        raise OSError(messages.DOWNLOAD_STOPPED)
    yield on_bytes


class _Install(unittest.TestCase):
    """An installed Amaze holding one add-on, beside another file of the user's."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_updates_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.install = os.path.join(self.dir, "Amaze")
        self.reset()
        test_support.put(self.dir, "the user's.txt", "kept")

    def reset(self) -> None:
        """The old Amaze, whole, with its add-on, and nothing beside it."""
        shutil.rmtree(self.install, True)
        shutil.rmtree(self.install + guard.ASIDE, True)
        self.lay_out(self.install, "old")
        test_support.put(self.install, "addons/example/otls/one.hda", "add-on")

    def lay_out(self, folder, version) -> None:
        for entry in ENTRIES:
            test_support.put(folder, entry if "." in entry else entry + "/a.txt", version)

    def version_in(self, folder):
        """The version every entry of the Amaze in `folder` holds, with its add-on; None if not whole."""
        found = {test_support.library_state(folder).get(e if "." in e else e + "/a.txt")
                 for e in ENTRIES}
        add_on = os.path.isfile(os.path.join(folder, "addons", "example", "otls", "one.hda"))
        return found.pop().decode() if len(found) == 1 and add_on and None not in found else None

    def found(self, payload, size=None, digest=None, body=None) -> updater.Update:
        test_support.serve(self, lambda url, headers: payload if body is None else body)
        return updater.Update(updater.NEWER, version="9.9", url=URL, sentence="newer",
                              size=len(payload) if size is None else size,
                              digest=digest or "sha256:" + hashlib.sha256(payload).hexdigest())

    def state(self) -> dict:
        return test_support.library_state(self.dir)

    def refused(self, found, *patches) -> str:
        """The install of `found`, with `(object, name, value)` patches, changes no file."""
        before = self.state()
        with contextlib.ExitStack() as stack:
            for target, name, value in patches:
                stack.enter_context(mock.patch.object(target, name, value))
            with self.assertRaises(OSError) as caught:
                updater.install(found, self.install)
        self.assertEqual(before, self.state(), "a refused update changed a file")
        return str(caught.exception)


class UpdateTest(_Install):

    def test_up01_an_update_cut_off_anywhere_leaves_one_whole_amaze(self):
        staged = os.path.join(self.dir, "Amaze.update", "staged")
        counting = faults.FaultDisk()
        self.lay_out(staged, "new")
        updater.apply_update(staged, self.install, disk=counting)
        between = []
        for step in range(1, counting.steps + 1):
            with self.subTest(crash_at=step):
                self.reset()
                self.lay_out(staged, "new")
                with self.assertRaises(faults.Cut):
                    updater.apply_update(staged, self.install, faults.FaultDisk(cut_at=step))
                if os.path.isdir(self.install):
                    self.assertIn(self.version_in(self.install), ("old", "new"))
                else:
                    between.append(step)
                    self.assertEqual("old", self.version_in(self.install + guard.ASIDE))
        self.assertEqual(1, len(between), "more than the one instant between the two renames")
        shutil.rmtree(staged, True)
        self.reset()
        self.refused(self.found(release()), (helpers, "download_operation", esc_during_download))
        self.refused(self.found(release()), (shutil, "copytree", full_disk("")))

    def test_up02_only_a_complete_download_matching_the_release_installs(self):
        payload = release()
        short = test_support.Reply(payload[:-50], {"Content-Length": str(len(payload))})
        cases = {"short": (None, None, short),
                 "another size": (len(payload) + 1, None, None),
                 "another checksum": (None, "sha256:" + "0" * 64, None),
                 "a checksum Amaze cannot compute": (None, "md9:00", None)}
        for name, (size, digest, body) in cases.items():
            with self.subTest(name):
                self.refused(self.found(payload, size, digest, body))

    def test_up03_nothing_is_written_outside_its_folder_and_oversize_is_refused(self):
        self.refused(self.found(release(extra={"Amaze/../../escaped.txt": "x"})))
        with self.subTest("a download bigger than a release"):
            self.refused(self.found(release()), (updater, "MAX_DOWNLOAD_BYTES", 100))
        with self.subTest("an archive unpacking bigger than a release"):
            self.refused(self.found(release()), (updater, "MAX_UNPACKED_BYTES", 10))

    def test_up04_an_update_installs_only_amazes_own_files(self):
        updater.install(self.found(release(extra={"Amaze/README.md": "x", "Amaze/tools/t": "x"})),
                        self.install)
        self.assertEqual(sorted(ENTRIES + ("addons",)), sorted(os.listdir(self.install)))
        self.refused(self.found(release("9.10", drop=("toolbar",))))

    def test_up05_an_update_keeps_every_add_on_or_installs_nothing(self):
        updater.install(self.found(release()), self.install)
        self.assertEqual("9.9", self.version_in(self.install), "the add-on was not kept")
        self.refused(self.found(release("9.10")), (shutil, "copytree", full_disk("addons")))

    def test_up06_a_library_changing_update_installs_only_on_continue(self):
        import hou
        import xml.etree.ElementTree as ET
        shelf = os.path.join(os.path.dirname(__file__), *[os.pardir] * 4, "toolbar", "Amaze.shelf")
        script = [tool for tool in ET.parse(shelf).getroot().findall("tool")
                  if tool.get("name") == "amaze_check_updates"][0].find("script").text
        library = os.path.join(self.dir, "library")
        prefs_mod.create_library(library)
        found = updater.Update(updater.NEWER, version="9.9", url=URL, sentence="newer",
                               library_version=library_policy.LIBRARY_VERSION + 1,
                               library_since="9.9")
        cases = {"Continue": (lambda default, close: 0, True),
                 "Cancel": (lambda default, close: 1, False),
                 "Esc": (lambda default, close: close, False),
                 "Return": (lambda default, close: default, False)}
        for name, (choice, installs) in cases.items():
            warned = []

            def display(text, buttons=(), default_choice=0, close_choice=-1, **how):
                if text != messages.LIBRARY_UPDATE_WARNING % "9.9":
                    return 0    # Install Update
                warned.append(text)
                return choice(default_choice, close_choice)

            with self.subTest(name), \
                    mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=display),
                                      create=True), \
                    mock.patch.object(updater, "check", return_value=found), \
                    mock.patch.object(updater, "configured_library", return_value=library), \
                    mock.patch.object(updater, "install") as install:
                exec(compile(script, "Amaze.shelf", "exec"), {})
                self.assertEqual([messages.LIBRARY_UPDATE_WARNING % "9.9"], warned)
                self.assertEqual(installs, install.called)

    def test_up07_an_older_amaze_reads_the_release_format_where_it_looks(self):
        here = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "library_policy.py")
        self.assertTrue(updater.LIBRARY_POLICY_URL.endswith(
            "/scripts/python/amaze/core/library_policy.py"))
        with open(here, "rb") as handle:
            test_support.serve(self, lambda url, headers, text=handle.read(): text)
        self.assertEqual((library_policy.LIBRARY_VERSION, library_policy.LIBRARY_VERSION_SINCE,
                          (library_policy.DATABASE_FORMAT, library_policy.RECORD_FORMAT)),
                         updater.release_library("9.9"))

    def test_up08_a_library_older_than_2_0_is_never_marked_3_0(self):
        old = os.path.join(self.dir, "old")
        test_support.put(old, guard.MASTER, {library_settings.POLICY: {
            library_settings.VERSION_ENTRY: {"version": 3}}})
        self.assertEqual(messages.LIBRARY_OLDER_THAN_2_0, library_actions.index_unopenable(old))
        self.assertFalse(library_actions.update(types.SimpleNamespace(dir=old)))
        self.assertEqual(3, library_settings.library_version(old))
        before_versions = os.path.join(self.dir, "before_versions")    # as Amaze 1.33 left one
        test_support.put(before_versions, "policy.json", '{"library_version": 2}')
        test_support.put(before_versions, "materials.json", "{}")
        state = test_support.library_state(before_versions)
        self.assertTrue(library_actions.folder_not_empty_without_library(before_versions))
        library_actions.prepare(types.SimpleNamespace(dir=before_versions))
        self.assertEqual(state, test_support.library_state(before_versions))

    def test_up10_after_an_install_houdini_keeps_working_and_is_told_to_restart(self):
        import hou
        from amaze.dialogs import update_dialog
        found = self.found(release())
        said = []
        with mock.patch.object(hou, "ui", types.SimpleNamespace(
                displayMessage=lambda text, **how: said.append(text)), create=True), \
                mock.patch.object(updater, "install_root", lambda: self.install):
            self.assertTrue(update_dialog.install_and_report(found))
        self.assertEqual([messages.UPDATE_INSTALLED % "9.9"], said)
        self.assertIn("Restart Houdini", messages.UPDATE_INSTALLED)
        self.assertEqual("9.9", self.version_in(self.install))

    def test_up20_a_check_asks_the_release_list_once_and_installs_nothing(self):
        before = self.state()
        asked = test_support.serve(self, lambda url, headers: {"tag_name": "0.1.0"})
        self.assertEqual(updater.UP_TO_DATE, updater.check("1.0.0").verdict)
        self.assertEqual([updater.RELEASES_URL], asked)
        self.assertEqual(before, self.state())

    def test_up21_only_a_newer_release_is_offered_compared_as_numbers(self):
        self.assertTrue(updater.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(updater.is_newer("1.9.0", "1.10.0"))
        import urllib.error
        for error, verdict in ((urllib.error.HTTPError(URL, 404, "", {}, None),
                                updater.NO_RELEASE), (OSError("offline"), updater.UNREACHABLE)):
            test_support.serve(self, lambda url, headers, error=error: error)
            self.assertEqual(verdict, updater.check("1.0.0").verdict)

    def test_up22_the_offer_names_the_format_the_library_will_have(self):
        library = os.path.join(self.dir, "library")
        prefs_mod.create_library(library)
        newer = updater.Update(updater.NEWER, version="9.9", sentence="newer",
                               library_version=library_policy.LIBRARY_VERSION,
                               formats=(library_policy.DATABASE_FORMAT + 1,
                                        library_policy.RECORD_FORMAT))
        self.assertEqual(messages.UPDATE_LIBRARY_AVAILABLE % ("9.9", "3.4"),
                         updater.offer_line(newer, library))
        unread = updater.Update(updater.NEWER, version="9.9", sentence="newer")
        self.assertEqual("newer", updater.offer_line(unread, library))
        self.assertTrue(re.match(r"\d+\.\d+$", library_settings.version_label(
            library_settings.library_formats(library))))


class OpeningTest(unittest.TestCase):
    """A pane on a fixture library, and copies of it in other formats to open."""

    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.pane = test_support.fixture_pane(self)
        self.first = self.pane.prefs.dir

    def library(self, version: int) -> tuple:
        """A copy of the fixture library as an Amaze of library `version` left it: (folder, Sage)."""
        folder = test_support.seeded_library(self)
        sage = users.create(types.SimpleNamespace(dir=folder, library_user=""), "Sage",
                            library=folder)
        library_db.release(types.SimpleNamespace(dir=folder))
        test_support.set_library_version(folder, version)
        return folder, sage

    def answering(self):
        """`hou.ui` answering Cancel to every message; each message's text is kept."""
        import hou
        self.asked = []

        def message(text, buttons=("OK",), **_how):
            self.asked.append(text)
            return len(buttons) - 1
        return mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=message),
                                 create=True)

    def test_up23_a_library_an_older_amaze_wrote_takes_this_format_at_once_unasked(self):
        older, _sage = self.library(library_policy.FORMAT_3_0[0])
        self.assertLess(library_settings.library_formats(older), library_settings.THIS_AMAZE)
        with self.answering():
            self.assertTrue(test_support.apply_library(self, types.SimpleNamespace(
                pane=self.pane), older, user="Sage"))
        self.assertEqual(([], library_settings.THIS_AMAZE),
                         (self.asked, library_settings.library_formats(older)))

    def test_up24_a_library_a_newer_amaze_wrote_stays_closed_and_update_is_offered_once_idle(self):
        newer, sage = self.library(library_policy.LIBRARY_VERSION + 1)
        settings = os.path.join(self.pane.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            named = dict(json.load(handle), directory=newer, library_user=sage)
        test_support.put(self.pane.prefs.path, "settings.json", json.dumps(named))
        with self.answering(), mock.patch.object(prefs_mod.Prefs, "save",
                                                 persistence._Persistence.save):
            self.pane.library.reload()
            with open(settings, encoding="utf-8") as handle:
                stayed = (self.pane.library.models_dir, json.load(handle)["directory"],
                          list(self.asked))
            test_support.pump_until(lambda: self.asked, 2)
        self.assertEqual((self.first, self.first, []), stayed, "it opened, or asked at once")
        self.assertEqual([messages.LIBRARY_NEEDS_NEWER_AMAZE % library_settings.version_label(
            library_settings.library_formats(newer))], self.asked)

    def test_up25_preferences_says_what_apply_will_do_and_shows_the_format_after_it(self):
        from amaze.dialogs import prefs_window
        label, this = library_settings.version_label, library_settings.THIS_AMAZE
        older, _sage = self.library(library_policy.FORMAT_3_0[0])
        newer, _sage = self.library(library_policy.LIBRARY_VERSION + 1)
        shown = prefs_window.AmazePrefsState(self.pane.prefs, pane=self.pane)
        lines = {}
        for folder in (self.first, older, newer):
            shown.pick_library(folder)
            lines[folder] = (shown.libraryFormat, shown.applyLine)
        formats = amazetheme.LABEL_LIBRARY_FORMAT
        self.assertEqual({self.first: (formats % label(this), ""),
                          older: (formats % label(library_settings.library_formats(older)),
                                  amazetheme.LABEL_UPGRADES_LIBRARY % label(this)),
                          newer: (formats % label(library_settings.library_formats(newer)),
                                  amazetheme.LABEL_LIBRARY_TOO_NEW)}, lines)
        with self.answering():
            self.assertFalse(test_support.apply_library(self, types.SimpleNamespace(
                pane=self.pane), newer, user="Sage", state=shown))
            test_support.pump_until(lambda: self.asked, 0.2)    # an open tried offers Update
            self.assertEqual((self.first, []), (self.pane.library.models_dir, self.asked),
                             "Apply was not refused")
            self.assertTrue(test_support.apply_library(self, types.SimpleNamespace(
                pane=self.pane), older, user="Sage", state=shown))
        self.assertEqual((formats % label(this), ""), (shown.libraryFormat, shown.applyLine))

if __name__ == "__main__":
    unittest.main()
