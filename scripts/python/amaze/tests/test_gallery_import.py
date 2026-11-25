"""Gallery Import: one test per requirement in docs/requirements/gallery-import.md."""

import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import debug, gallery_import  # noqa: E402
from amaze.render import nodes, thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _entries(count):
    """`count` gallery entries as Houdini gives them, each making a node with the id `id<n>`."""
    made = []
    for n in range(count):
        node = mock.Mock(name="node%d" % n)
        node.userData.return_value = "id%d" % n
        node.name.return_value = "entry%d" % n
        entry = mock.Mock()
        entry.canCreateChildNode.return_value = True
        entry.createChildNode.return_value = node
        entry.name.return_value = "entry%d" % n
        made.append((entry, "mtlxstandard_surface", "Metal" if n % 2 else "Wood"))
    return made


def _library(count, render_on_import=1):
    """A materials model holding `id0`..`id<count-1>`, as the batch render reads it."""
    rows = [types.SimpleNamespace(mat_id="id%d" % n) for n in range(count)]
    return types.SimpleNamespace(
        preferences=types.SimpleNamespace(render_on_import=render_on_import), assets=rows,
        find_asset_row_by_id=lambda key: next(
            (n for n, row in enumerate(rows) if row.mat_id == key), -1))


class GalleryImportTest(unittest.TestCase):

    def gallery(self, name, make=lambda name: hou.node("/mat").createNode("subnet", name)) -> str:
        """A real .gal holding one entry of the node `make(name)` makes, not installed; its path."""
        folder = tempfile.mkdtemp(prefix="amaze_gallery_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, name + ".gal")
        node = make(name)
        try:
            self.assertIsNotNone(hou.galleries.createGalleryEntry(path, name, node))
        finally:
            node.destroy()
        self.addCleanup(hou.galleries.removeGallery, path)
        hou.galleries.removeGallery(path)    # creating it installed it
        return path

    def test_gi01_gallery_import_leaves_the_scene_as_it_was(self):
        path = self.gallery("amaze_gi01")
        scene = [node.path() for node in hou.node("/").allSubChildren()]
        undos = hou.undos.undoLabels()
        answers = iter([True, hou.OperationFailed("refused")])

        def save(node, *args, **how):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with gallery_import.opened(path) as entries:
            summary = gallery_import.import_entries(save, entries * 2)
        self.assertEqual((1, 1), (summary["imported"], summary["failed"]))
        self.assertEqual(scene, [node.path() for node in hou.node("/").allSubChildren()])
        self.assertEqual(undos, hou.undos.undoLabels(), "the import left an undo step")

    def test_gi02_houdinis_gallery_list_is_left_as_found(self):
        path = self.gallery("amaze_gi02")
        for installed in (False, True):
            if installed:
                hou.galleries.installGallery(path)
            with gallery_import.opened(path) as entries:
                self.assertEqual(1, len(entries))
            self.assertEqual(installed, hou.galleries.removeGallery(path), "not left as found")
        hou.galleries.installGallery(path)
        with mock.patch.object(hou.galleries, "installGallery", return_value=None), \
                mock.patch.object(debug, "alert") as alert, \
                gallery_import.opened(path) as entries:
            self.assertEqual([], entries)
        alert.assert_called_once_with(messages.GALLERY_NOT_PUT_BACK % path,
                                      key="gallery-not-put-back")

    def test_gi21_each_material_entry_is_saved_in_its_category_tagged_gallery(self):
        saved = []
        entries = _entries(2)
        entries[1][0].canCreateChildNode.return_value = False
        summary = gallery_import.import_entries(lambda *args: saved.append(args[1:]) or "ok",
                                                entries)
        self.assertEqual([("Wood", "gallery", False)], saved)
        self.assertEqual((1, 1), (summary["imported"], summary["skipped"]))
        entry = mock.Mock()
        entry.categories.return_value = ["Materials/Metals/", ""]
        self.assertEqual("Metals", gallery_import._category_of(entry))
        entry.categories.return_value = []
        self.assertEqual("Gallery", gallery_import._category_of(entry))

    def test_gi22_a_failed_entry_is_counted_and_the_rest_go_on(self):
        answers = iter(["", "ok", "ok"])
        summary = gallery_import.import_entries(lambda *a, **k: next(answers), _entries(3))
        self.assertEqual((2, 1), (summary["imported"], summary["failed"]))

    def test_gi24_one_render_batch_at_the_end_after_esc_too_and_none_when_off(self):
        def esc_at_third(index, total, name):
            if index == 2:
                raise hou.OperationInterrupted()

        for on, expected in ((1, [["id0", "id1"]]), (0, [])):
            batches, summary = [], {}
            with self.subTest(render_on_import=on), \
                    mock.patch.object(thumbs.ThumbNailRenderer, "render_assets",
                                      lambda prefs, mats: batches.append(
                                          [m.mat_id for m in mats])), \
                    self.assertRaises(hou.OperationInterrupted):
                gallery_import.import_entries(lambda *a, **k: "ok", _entries(4), summary=summary,
                                              progress=esc_at_third, library=_library(4, on))
            self.assertEqual(expected, batches)
            self.assertEqual(2, summary["imported"], "Esc lost what was saved")


class _Esc:
    """`hou.InterruptableOperation` whose Esc is pressed as the second entry starts."""

    def __init__(self, *args, **how) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    @staticmethod
    def updateLongProgress(fraction, text) -> None:
        if fraction > 0:
            raise hou.OperationInterrupted()


class InThePaneTest(unittest.TestCase):
    """Import Gallery as a pane on a fixture library runs it, renders off; each message kept."""

    def gallery(self, name) -> str:
        """A real .gal holding one Karma material, which a save takes; its path."""
        def karma(name):
            return nodes.build_karma_material(hou.node("/mat"), name, lambda builder: (
                builder.createNode("mtlxstandard_surface", "surface"))).builder
        return GalleryImportTest.gallery(self, name, karma)

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # the save checks it; nothing renders
        self.pane = test_support.fixture_pane(self)
        self.pane.prefs.render_on_import = 0
        self.model, self.said = self.pane.material_model, []

    def run_import(self, path, *more, answer=0, repeat=1):
        """Import `path`'s entries `repeat` times, then the entries `more`, answering `answer`."""
        def message(text, buttons=("OK",), **how):
            self.said.append((text, len(self.model.assets)))
            return answer if buttons == messages.BUTTONS_IMPORT else 0

        with mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=message),
                               create=True), gallery_import.opened(path) as entries:
            self.pane.saving._import_gallery(path, entries * repeat + list(more))
            return entries[0][1]

    def test_gi20_nothing_is_imported_before_the_list_is_confirmed_and_cancel_imports_nothing(self):
        path, rows = self.gallery("amaze_gi20"), len(self.model.assets)
        kind = self.run_import(path, answer=1)
        asked = messages.IMPORT_MATERIAL_PRESETS_FROM % (1, os.path.basename(path), "  1 x " + kind)
        self.assertEqual([(asked, rows)], self.said, "Cancel imported, or no list was asked")
        self.said.clear()
        self.run_import(path)
        self.assertEqual((asked, rows), self.said[0], "imported before the list was confirmed")
        self.assertEqual(rows + 1, len(self.model.assets))

    def test_gi23_esc_stops_the_import_and_what_was_saved_stays_in_the_sidebar(self):
        path, before = self.gallery("amaze_gi23"), test_support.asset_ids(self.model)
        with mock.patch.object(hou, "InterruptableOperation", _Esc):
            self.run_import(path, repeat=2)
        saved, = test_support.arrived(self.model, before)
        self.assertTrue(self.pane.sidebar.model.index_of(saved.categories[0]).isValid(),
                        "its category is not in the sidebar")
        self.assertEqual(messages.GALLERY_IMPORT_INTERRUPTED % (1, 0, 0), self.said[-1][0])

    def test_gi25_the_closing_message_counts_the_imported_skipped_and_failed(self):
        skipped, failed = mock.Mock(), mock.Mock()
        skipped.canCreateChildNode.return_value = False
        failed.createChildNode.side_effect = hou.OperationFailed("refused")
        self.run_import(self.gallery("amaze_gi25"), (skipped, "subnet", "Gallery"),
                        (skipped, "subnet", "Gallery"), (failed, "subnet", "Gallery"))
        self.assertEqual(messages.GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED % (1, 2, 1),
                         self.said[-1][0])

if __name__ == "__main__":
    unittest.main()
