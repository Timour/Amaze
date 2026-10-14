"""One Karma scaffold per BATCH, not per material - counted rather than timed, because the claim is a count of builds against renders, and a wall-clock assertion on a real Karma render is a flaky test about the machine."""

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

from amaze.render import thumbs  # noqa: E402
from amaze import preview  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class TheScaffoldIsBuiltOncePerBatch(unittest.TestCase):  # the scaffold is a full USD stage composition - the expensive half of a Karma thumbnail, and byte-identical for every material, so one scaffold per material pays the stage load N times

    def _model(self, count):
        from amaze.core import library
        model = library.MaterialLibrary.__new__(library.MaterialLibrary)
        model.preferences = test_support.fixture_prefs(self)
        model._assets = [mock.Mock(name="asset%d" % i) for i in range(count)]
        model._add_thumb_paths = lambda row: None
        model.rowCount = lambda: len(model._assets)
        return model

    def test_ten_materials_build_one_scaffold(self):
        model = self._model(10)
        built = []
        rendered = []

        def fake_build(preferences):
            built.append(1)
            return {"net": mock.Mock()}

        with mock.patch.object(preview, "build_karma_scaffold",
                               fake_build), \
             mock.patch.object(thumbs.ThumbNailRenderer, "create_thumbnail",
                               lambda self, scaffold=None:
                               rendered.append(scaffold)):
            model.render_thumbnails(list(range(10)))

        self.assertEqual(1, len(built),
                         "the USD stage was composed %d times for one "
                         "batch of ten" % len(built))
        self.assertEqual(10, len(rendered), "not every material rendered")
        self.assertTrue(
            all(s is rendered[0] for s in rendered),
            "the materials did not all render into the SAME scaffold")

    def test_a_single_render_is_a_batch_of_one(self):
        """render_thumbnail keeps working and takes the same path - no second way to render one material."""
        model = self._model(1)
        built = []
        with mock.patch.object(
                preview, "build_karma_scaffold",
                lambda preferences: built.append(1) or {"net": mock.Mock()}), \
             mock.patch.object(thumbs.ThumbNailRenderer, "create_thumbnail",
                               lambda self, scaffold=None: None):
            model.render_thumbnail(0)
        self.assertEqual(1, len(built))

    def test_the_batch_destroys_its_scaffold_once(self):
        """Both ends, and off the undo stack - a bare destroy is the half that resurrects the whole scaffold on one Ctrl+Z."""
        net = mock.Mock()
        with mock.patch.object(preview, "build_karma_scaffold",
                               lambda preferences: {"net": net}):
            with thumbs.ThumbNailRenderer.karma_batch(
                    test_support.fixture_prefs(self)) as scaffold:
                self.assertIsNotNone(scaffold)
                net.destroy.assert_not_called()
        net.destroy.assert_called_once()


class WithNoSceneViewerNothingIsImported(unittest.TestCase):
    """Every renderer takes OCIO from a Scene Viewer, so with none open nothing in a batch renders."""

    def test_two_rows_import_nothing_and_say_so_once(self):
        from amaze import messages
        from amaze.core import library
        from amaze.render import nodes
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library.MaterialLibrary(
            preferences=test_support.fixture_prefs(self))
        shown, imported = [], []
        desktop = types.SimpleNamespace(paneTabOfType=lambda kind: None)
        ui = types.SimpleNamespace(
            curDesktop=lambda: desktop, paneTabs=lambda: (),
            displayMessage=lambda text, *a, **k: shown.append(text))
        real = nodes.NodeHandler.import_asset_to_scene

        def spy(handler, mat, *args, **kwargs):
            imported.append(mat.name)
            return real(handler, mat, *args, **kwargs)

        with mock.patch.object(hou, "ui", ui, create=True), \
                mock.patch.object(nodes.NodeHandler,
                                  "import_asset_to_scene", spy):
            model.render_thumbnails([0, 1])
        self.assertEqual(
            [], imported,
            "Update Preview imported every row before finding that "
            "nothing can render without a Scene Viewer")
        self.assertEqual([messages.NO_SCENE_VIEWER_FOR_THUMBNAIL], shown,
                         "the batch did not say why, exactly once")


if __name__ == "__main__":
    unittest.main()
