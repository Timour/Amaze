"""The Add-On page: a row per package group, its switch from Apply, and the one button."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import messages  # noqa: E402
from amaze.core import addons, updater  # noqa: E402
from amaze.dialogs import prefs_window  # noqa: E402
from amaze.tests import test_support  # noqa: E402

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="54" height="54">'
       '<rect width="54" height="54" fill="#c04040"/></svg>')
URL = "https://example.invalid/addons/%s-%s.amazepkg"


def _node(label, kind, picture, short, group=None):
    node = {"label": label, "type": "Sop/example::%s::0.1" % kind,
            "file": "otls/example_%s.hda" % kind, "addon_icon": picture,
            "short_description": short, "description": "%s's help." % label}
    if group is not None:
        node["group"] = group
    return node


class _Tab(unittest.TestCase):
    """Preferences over an Amaze root holding `NODES` as one add-on, when there are any."""

    NODES = ()
    VERSION = "1.2.3"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_addon_tab_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root = os.path.join(self.dir, "Amaze")
        os.makedirs(self.root)
        if self.NODES:
            self._install()
        patcher = mock.patch.object(updater, "install_root", lambda: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = prefs_window.AmazePrefsState(test_support.fixture_prefs(self), pane=None)

    def _install(self):
        source = os.path.join(self.dir, "source")
        files = sorted({node["file"] for node in self.NODES} | {n["addon_icon"] for n in self.NODES})
        for member in files:
            path = os.path.join(source, *member.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(SVG if member.endswith(".svg") else member)
        fields = {"name": "Example", "folder": "example", "version": self.VERSION,
                  "author": "Test Author", "houdini": "22.0.466", "houdini_min": "22.0",
                  "changelog": "- A change.", "nodes": list(self.NODES)}
        store = os.path.join(self.dir, "store")
        os.makedirs(store)
        package = addons.write(store, fields, source, files)
        addons.install(package, self.root, running=(22, 0, 466))

    def line(self):
        return self.state.addonsLine


class TheRowsComeFromThePackagesTest(_Tab):

    NODES = (_node("Alpha", "alpha", "pictures/pair.svg", "Does two things.", group="Pair"),
             _node("Beta", "beta", "pictures/pair.svg", "Does two things.", group="Pair"),
             _node("Gamma", "gamma", "pictures/gamma.svg", "Does a third."),
             _node("Delta", "delta", "pictures/gamma.svg", "Does a fourth."))

    def test_each_group_is_one_row_named_and_described_by_its_package(self):
        rows = self.state.addonRows
        self.assertEqual(["Pair", "Gamma", "Delta"], [row["label"] for row in rows])
        self.assertEqual(["Does two things.", "Does a third.", "Does a fourth."],
                         [row["description"] for row in rows])
        self.assertEqual(("version 1.2.3", "author: Test Author"),
                         (rows[0]["version"], rows[0]["author"]))
        self.assertEqual("Alpha&#x27;s help.<br><br>Beta&#x27;s help.", rows[0]["tip"])
        picture = QtCore.QUrl(rows[0]["picture"]).toLocalFile()
        self.assertTrue(picture.endswith("pictures/pair.svg") and os.path.isfile(picture),
                        "the package's picture")

    def test_turning_a_row_off_moves_its_files_from_apply_and_shows_a_restart_is_due(self):
        pair = self.state.addonRows[0]["pref"]
        manifest = addons.installed(self.root, "example")
        self.assertTrue(self.state.getBool(pair))
        self.state.setPref(pair, "0")    # what its switch sends
        self.assertTrue(addons.is_on(self.root, "example", addons.rows(manifest)[0]),
                        "the files moved before Apply")
        self.assertTrue(self.state.addonsAltered, "nothing says a restart is due")
        self.state.apply()
        self.assertFalse(addons.is_on(self.root, "example", addons.rows(manifest)[0]))
        self.assertEqual(messages.ADDONS_TURNED % ("Pair", "off"), self.line())

    def test_a_check_offers_what_is_newer_and_update_installs_it(self):
        store = {"Example": ("1.3.0", URL % ("Example", "1.3.0")),
                 "Other": ("0.1.0", URL % ("Other", "0.1.0"))}
        with mock.patch.object(addons, "store_versions", lambda betas=False: store):
            self.state.pressAddons()
        self.assertEqual("Update", self.state.addonsLabel)
        self.assertEqual(messages.ADDONS_AVAILABLE % "Example 1.3.0, Other 0.1.0", self.line())
        fetched = []
        with mock.patch.object(addons, "fetch_and_install",
                               lambda url, root, running=None, **_kw: fetched.append(url)):
            self.state.pressAddons()
        self.assertEqual([URL % ("Example", "1.3.0"), URL % ("Other", "0.1.0")], fetched)
        self.assertEqual(messages.ADDONS_INSTALLED % "Example 1.3.0, Other 0.1.0", self.line())
        self.assertEqual("Check for Updates", self.state.addonsLabel)

    def test_update_passes_the_running_houdini_version_to_each_install(self):
        from amaze.helpers import hostver
        self.state._addons_found = [("Example", "1.3.0", URL % ("Example", "1.3.0"))]
        seen = []
        with mock.patch.object(addons, "fetch_and_install",
                               lambda url, root, running=None, **_kw: seen.append(running)):
            self.state.pressAddons()
        self.assertEqual([hostver.houdini_version()], seen,
                         "`fetch_and_install` got no `running` Houdini version")

    def test_nothing_newer_shows_every_add_on_is_up_to_date(self):
        with mock.patch.object(addons, "store_versions",
                               lambda betas=False: {"Example": ("1.2.3", URL % ("Example", "1.2.3"))}):
            self.state.pressAddons()
        self.assertEqual(messages.ADDONS_UP_TO_DATE, self.line())
        self.assertEqual("Check for Updates", self.state.addonsLabel)

    def test_the_beta_switch_installs_the_newest_beta_even_below_the_release(self):
        asked = []

        def store(betas=False):
            asked.append(betas)
            return {"Example": ("1.2.0-beta", URL % ("Example", "1.2.0-beta"))}

        self.state.setPref("addon_betas", "1")    # what the switch sends: checked before Apply
        with mock.patch.object(addons, "store_versions", store):
            self.state.pressAddons()
        self.assertEqual([True], asked)
        self.assertEqual(messages.ADDONS_AVAILABLE % "Example 1.2.0-beta", self.line())

    def test_turning_the_beta_switch_clears_what_the_last_check_found(self):
        with mock.patch.object(addons, "store_versions",
                               lambda betas=False: {"Example": ("1.3.0", URL % ("Example", "1.3.0"))}):
            self.state.pressAddons()
        self.assertEqual("Update", self.state.addonsLabel)
        self.state.setPref("addon_betas", "1")    # what the switch sends
        self.assertEqual("Check for Updates", self.state.addonsLabel)

    def test_an_unreachable_store_is_shown_in_the_status_line(self):
        def offline(betas=False):
            raise OSError("offline")

        with mock.patch.object(addons, "store_versions", offline):
            self.state.pressAddons()
        self.assertEqual(messages.ADDONS_STORE_UNREACHABLE % "offline", self.line())


class ABetaInstalledTest(_Tab):

    NODES = (_node("Gamma", "gamma", "pictures/gamma.svg", "Does a third."),)
    VERSION = "1.2.4-beta"

    def test_its_row_shows_its_beta_and_a_release_check_offers_the_release(self):
        self.assertEqual("version 1.2.4-beta", self.state.addonRows[0]["version"])
        with mock.patch.object(addons, "store_versions",
                               lambda betas=False: {"Example": ("1.2.3", URL % ("Example", "1.2.3"))}):
            self.state.pressAddons()
        self.assertEqual(messages.ADDONS_AVAILABLE % "Example 1.2.3", self.line())


class NoAddOnInstalledTest(_Tab):

    def test_the_list_shows_none_is_installed(self):
        self.assertEqual([], self.state.addonRows)
        self.assertEqual(messages.ADDONS_NONE, self.state.addonsNone)


if __name__ == "__main__":
    unittest.main()
