"""The Add-On tab: package rows on the drawn rows, the switch, and the button."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme, messages  # noqa: E402
from amaze.core import addons, updater  # noqa: E402
from amaze.dialogs import prefs_dialog  # noqa: E402
from amaze.helpers import theme  # noqa: E402
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
        self.dialog = prefs_dialog.PrefsDialog(test_support.fixture_prefs(self), panel=None)
        self.addCleanup(self.dialog.deleteLater)

    def _install(self):
        source = os.path.join(self.dir, "source")
        files = sorted({node["file"] for node in self.NODES} | {n["addon_icon"] for n in self.NODES})
        for member in files:
            path = os.path.join(source, *member.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(SVG if member.endswith(".svg") else member)
        fields = {"name": "Example", "folder": "example", "version": "1.2.3",
                  "author": "Test Author", "houdini": "22.0.466", "houdini_min": "22.0",
                  "changelog": "- A change.", "nodes": list(self.NODES)}
        store = os.path.join(self.dir, "store")
        os.makedirs(store)
        package = addons.write(store, fields, source, files)
        addons.install(package, self.root, running=(22, 0, 466))

    def line(self):
        return self.dialog._lbl_addons.text()


class TheRowsAreThePackagesOwnTest(_Tab):

    NODES = (_node("Alpha", "alpha", "pictures/pair.svg", "Does two things.", group="Pair"),
             _node("Beta", "beta", "pictures/pair.svg", "Does two things.", group="Pair"),
             _node("Gamma", "gamma", "pictures/gamma.svg", "Does a third."),
             _node("Delta", "delta", "pictures/gamma.svg", "Does a fourth."))

    def test_each_group_is_one_row_named_and_described_by_its_package(self):
        rows = self.dialog.addon_rows
        self.assertEqual(["Pair", "Gamma", "Delta"], [row["ToggleSwitch"].text() for row in rows])
        self.assertEqual(["Does two things.", "Does a third.", "Does a fourth."],
                         [row["add-on short description"].text() for row in rows])
        self.assertEqual(("version 1.2.3", "author: Test Author"),
                         (rows[0]["add-on version"].text(), rows[0]["add-on author"].text()))
        self.assertEqual("Alpha's help.\n\nBeta's help.",
                         rows[0]["add-on short description"].toolTip())
        self.assertFalse(rows[0]["add-on picture"].pixmap().isNull(), "the package's picture")

    def test_every_row_lands_on_the_drawn_rows(self):
        """The first row as drawn, the second as drawn, the third one pitch below the second."""
        drawn = {}
        for kind, x, y, w, h, _text in amazetheme.DIALOG_LAYOUT["P05"]["nodes"]:
            drawn.setdefault(kind, []).append((x, y, w, h))
        left, top = drawn["QTextBrowser"][0][:2]
        rows = self.dialog.addon_rows
        self.assertEqual(3, len(rows))
        for index, row in enumerate(rows):
            for kind, widget in row.items():
                x, y, w, h = drawn[kind][0 if kind.startswith("QWidget") else min(index, 1)]
                y += amazetheme.P05_ROW_PITCH if index == 2 else 0
                with self.subTest(row=index, kind=kind):
                    self.assertEqual((theme.ui_px(x - left), theme.ui_px(y - top)),
                                     (widget.x(), widget.y()))
                    if kind in ("add-on short description", "QWidget ▸ group divider"):
                        self.assertEqual((theme.ui_px(w), theme.ui_px(h)),
                                         (widget.width(), widget.height()))

    def test_turning_a_row_off_moves_its_files_and_says_a_restart_is_due(self):
        pair = self.dialog.addon_rows[0]["ToggleSwitch"]
        self.assertTrue(pair.isChecked())
        pair.setChecked(False)
        manifest = addons.installed(self.root, "example")
        self.assertFalse(addons.is_on(self.root, "example", addons.rows(manifest)[0]))
        self.assertEqual(messages.ADDONS_TURNED % ("Pair", "off"), self.line())

    def test_a_check_offers_what_is_newer_and_update_installs_it(self):
        store = {"Example": ("1.3.0", URL % ("Example", "1.3.0")),
                 "Other": ("0.1.0", URL % ("Other", "0.1.0"))}
        with mock.patch.object(addons, "store_versions", lambda: store):
            self.dialog.check_addons()
        self.assertEqual("Update", self.dialog._btn_addons.text())
        self.assertEqual(messages.ADDONS_AVAILABLE % "Example 1.3.0, Other 0.1.0", self.line())
        fetched = []
        with mock.patch.object(addons, "fetch_and_install",
                               lambda url, root, running=None: fetched.append(url)):
            self.dialog.install_addons()
        self.assertEqual([URL % ("Example", "1.3.0"), URL % ("Other", "0.1.0")], fetched)
        self.assertEqual(messages.ADDONS_INSTALLED % "Example 1.3.0, Other 0.1.0", self.line())
        self.assertEqual("Check for Updates", self.dialog._btn_addons.text())

    def test_nothing_newer_says_every_add_on_is_up_to_date(self):
        with mock.patch.object(addons, "store_versions",
                               lambda: {"Example": ("1.2.3", URL % ("Example", "1.2.3"))}):
            self.dialog.check_addons()
        self.assertEqual(messages.ADDONS_UP_TO_DATE, self.line())
        self.assertEqual("Check for Updates", self.dialog._btn_addons.text())

    def test_an_unreachable_store_is_said_in_the_line(self):
        def offline():
            raise OSError("offline")

        with mock.patch.object(addons, "store_versions", offline):
            self.dialog.check_addons()
        self.assertEqual(messages.ADDONS_STORE_UNREACHABLE % "offline", self.line())


class NoAddOnInstalledTest(_Tab):

    def test_the_list_says_none_is_installed(self):
        self.assertEqual([], self.dialog.addon_rows)
        shown = [label.text() for label in self.dialog._addon_list.widget()
                 .findChildren(QtWidgets.QLabel)]
        self.assertEqual([messages.ADDONS_NONE], shown)


if __name__ == "__main__":
    unittest.main()
