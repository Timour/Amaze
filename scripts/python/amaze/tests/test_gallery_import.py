"""Gallery Import saves each entry through the save its caller hands in. ▸r/gallery-entries"""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402,F401

from amaze import messages  # noqa: E402
from amaze.core import gallery_import  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class EachEntryGoesThroughTheSaveHandedIn(unittest.TestCase):
    """The caller's `save` takes every entry; a refused save counts as failed, never imported."""

    def test_two_entries_one_refused(self):
        node = mock.Mock()
        entry = mock.Mock()
        entry.canCreateChildNode.return_value = True
        entry.createChildNode.return_value = node
        entry.name.return_value = "probe"
        saved = []
        answers = iter(["Karma", ""])
        summary = gallery_import.import_entries(
            lambda *args: saved.append(args) or next(answers),
            [(entry, "mtlxstandard_surface", "Metal"),
             (entry, "mtlxstandard_surface", "Wood")])
        self.assertEqual([(node, "Metal", "gallery", False),
                          (node, "Wood", "gallery", False)], saved)
        self.assertEqual((1, 1), (summary["imported"], summary["failed"]))


def _entries(count):
    """`count` gallery entries, each making its own node stamped `id<n>` once saved."""
    made = []
    for n in range(count):
        node = mock.Mock(name="node%d" % n)
        node.userData.return_value = "id%d" % n
        entry = mock.Mock()
        entry.canCreateChildNode.return_value = True
        entry.createChildNode.return_value = node
        entry.name.return_value = "entry%d" % n
        made.append((entry, "mtlxstandard_surface", "Metal" if n % 2 else "Wood"))
    return made


class AnInterruptKeepsWhatLanded(unittest.TestCase):
    """Esc raises out of `progress`; the summary the caller holds keeps what landed."""

    def test_the_callers_summary_holds_the_counts_and_categories(self):
        def progress(index, total, name):
            if index == 2:
                raise hou.OperationInterrupted()

        summary = {}
        with self.assertRaises(hou.OperationInterrupted):
            gallery_import.import_entries(lambda *args: "Karma", _entries(4),
                                          progress=progress, summary=summary)
        self.assertEqual(2, summary.get("imported"), summary)
        self.assertEqual({"Wood": 1, "Metal": 1}, summary.get("categories"), summary)

    def test_the_returned_summary_is_the_one_handed_in(self):
        summary = {}
        returned = gallery_import.import_entries(lambda *args: "Karma", _entries(1),
                                                 summary=summary)
        self.assertIs(summary, returned)
        self.assertEqual(1, summary["imported"])


class AGalleryImportRendersOnceAfterItsSaves(unittest.TestCase):
    """With the library handed in, each save skips its render and one batch follows. ▸r/husk-startup"""

    def _import(self, render_on_import, answers):
        from amaze.render import thumbs
        rows = [types.SimpleNamespace(mat_id="id%d" % n) for n in range(len(answers))]
        library = types.SimpleNamespace(
            preferences=types.SimpleNamespace(render_on_import=render_on_import),
            assets=rows, find_asset_row_by_id=lambda key: next(
                (n for n, row in enumerate(rows) if row.mat_id == key), -1))
        asked, batches = [], []
        replies = iter(answers)

        def save(*args, **kwargs):
            asked.append(kwargs)
            return next(replies)

        with mock.patch.object(thumbs.ThumbNailRenderer, "render_assets",
                               lambda prefs, mats: batches.append([m.mat_id for m in mats])):
            gallery_import.import_entries(save, _entries(len(answers)), library=library)
        return asked, batches

    def test_the_saves_skip_their_render_and_one_batch_renders_what_landed(self):
        asked, batches = self._import(1, ["Karma", "", "Karma"])
        self.assertEqual([{"render": False}] * 3, asked)
        self.assertEqual([["id0", "id2"]], batches, "not ONE batch of the saved rows")

    def test_render_thumbs_on_import_off_renders_nothing(self):
        self.assertEqual([], self._import(0, ["Karma"])[1])


class _Escaped:
    """`hou.InterruptableOperation` whose third progress report is the user's Esc."""

    def __init__(self, *_args, **_kwargs):
        self.reports = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def updateLongProgress(self, _fraction, _text):
        self.reports += 1
        if self.reports == 3:
            raise hou.OperationInterrupted()


class GalleryImportInThePanel(unittest.TestCase):
    """Gallery Import on a fixture panel: real saves, the summary the panel holds, one batch."""

    @classmethod
    def setUpClass(cls):
        if not hou.getenv("OCIO"):    # save_node refuses without one
            hou.putenv("OCIO", "/dev/null")

    def setUp(self):
        from amaze.render import thumbs
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 1
        self.said, self.batches = [], []
        ui = types.SimpleNamespace(
            selectFile=lambda *a, **k: "probe.gal",
            displayMessage=lambda text, *a, **k: self.said.append(text) or 0)
        for owner, name, value in (
                (hou, "ui", ui),
                (thumbs.ThumbNailRenderer, "render_assets", lambda prefs, mats:
                 self.batches.append(sorted(str(mat.mat_id) for mat in mats)))):
            patcher = mock.patch.object(owner, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _entries(self, categories):
        """One entry per category, each building a real MaterialX builder to save."""
        from amaze.render import nodes
        made = []
        for n, category in enumerate(categories):
            def build(parent, n=n):
                builder = nodes.make_karma_builder(parent, "gallery_probe_%d" % n)
                nodes.wire_builder_output(builder, builder.createNode("mtlxstandard_surface"))
                return builder

            entry = mock.Mock()
            entry.canCreateChildNode.return_value = True
            entry.createChildNode.side_effect = build
            entry.name.return_value = "gallery_probe_%d" % n
            made.append((entry, "subnet", category))
        return made

    def _import(self, categories):
        held = test_support.asset_ids(self.panel.material_model)
        with mock.patch.object(gallery_import, "entries_from_file",
                               lambda path: self._entries(categories)):
            self.panel.import_galleries()
        return sorted(str(mat.mat_id) for mat in
                      test_support.arrived(self.panel.material_model, held))

    def test_esc_keeps_what_landed_its_categories_and_its_counts(self):
        with mock.patch.object(hou, "InterruptableOperation", _Escaped):
            landed = self._import(["GalleryEscA", "GalleryEscB", "GalleryEscC"])
        self.assertEqual(2, len(landed), "premise: the Esc did not stop the third entry")
        shown = self.panel.get_category_names()
        self.assertEqual([True, True, False],
                         [name in shown for name in ("GalleryEscA", "GalleryEscB", "GalleryEscC")],
                         "the categories of what landed have no sidebar row")
        self.assertEqual(messages.GALLERY_IMPORT_INTERRUPTED % (2, 0, 0), self.said[-1])

    def test_what_landed_renders_in_one_batch_with_the_setting_left_on(self):
        landed = self._import(["GalleryBatchA", "GalleryBatchB"])
        self.assertEqual(2, len(landed), "premise: the gallery saved nothing")
        self.assertEqual([landed], self.batches, "not ONE batch of what landed")
        self.assertEqual(1, self.panel.prefs.render_on_import)
        self.assertEqual(messages.GALLERY_IMPORT_FINISHED_RENDERING % (2, 0, 0), self.said[-1])


if __name__ == "__main__":
    unittest.main()
