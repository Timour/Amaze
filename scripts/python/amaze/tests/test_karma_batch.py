"""One stage and ONE husk per BATCH, counted rather than timed: a clock test is about the machine."""

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

from amaze.render import husk_job, thumbs  # noqa: E402
from amaze import preview  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class ASelectionIsOneHuskPerRenderer(unittest.TestCase):
    """A husk's start-up is most of a thumbnail, so a batch pays it once. ▸r/husk-startup"""

    def _model(self, renderers):
        from amaze.core import library, material
        model = library.MaterialLibrary.__new__(library.MaterialLibrary)
        model.preferences = test_support.fixture_prefs(self)
        model._assets = [material.Material(name="m%d" % i, renderer=r)
                         for i, r in enumerate(renderers)]
        model._add_thumb_paths = lambda row: None
        model.rowCount = lambda: len(model._assets)
        return model

    def _batches(self, model, rows):
        from amaze.render import nodes
        batches = []

        def imported(handler, mat, *args, **kwargs):
            handler._builder_node = mock.Mock(name=mat.name)
            return True, "", []

        with mock.patch.object(preview, "ocio_from_viewer", lambda: {"display": "d"}), \
                mock.patch.object(nodes.NodeHandler, "import_asset_to_scene", imported), \
                mock.patch.object(nodes.NodeHandler, "cleanup"), \
                mock.patch.object(thumbs.ThumbNailRenderer, "render_batch",
                                  lambda prefs, renderer, items:
                                  batches.append((renderer, len(items)))):
            if len(rows) == 1:
                model.render_thumbnail(rows[0])
            else:
                model.render_thumbnails(rows)
        return batches

    def test_ten_materials_are_one_batch(self):
        model = self._model(["MaterialX"] * 10)
        self.assertEqual([("Karma", 10)], self._batches(model, list(range(10))))

    def test_karma_and_octane_are_a_batch_each(self):
        model = self._model(["MaterialX", "Octane", "MaterialX", "Octane"])
        self.assertEqual([("Karma", 2), ("Octane", 2)],
                         self._batches(model, [0, 1, 2, 3]))

    def test_a_single_render_is_a_batch_of_one(self):
        """render_thumbnail takes the same path: no second way to render one material."""
        self.assertEqual([("Karma", 1)], self._batches(self._model(["MaterialX"]), [0]))


class TheBatchWritesOneStage(unittest.TestCase):

    def test_ten_materials_one_stage_one_husk(self):
        net = mock.Mock()
        built, written, submitted = [], [], []

        def build(preferences, renderer="Karma"):
            built.append(renderer)
            return {"net": net}

        def write(scaffold, items, out_dir):
            written.append(len(items))
            return {"usd": "u", "prims": ["/m%d" % i for i in range(len(items))],
                    "ball": "/b", "renderer": "Karma", "ocio": ("d", "v", "s")}

        with mock.patch.object(preview, "build_usd_scaffold", build), \
                mock.patch.object(preview, "write_batch", write), \
                mock.patch.object(husk_job.jobs, "submit",
                                  lambda job, blocking=False: submitted.append(job)):
            ok = thumbs.ThumbNailRenderer.render_batch(
                test_support.fixture_prefs(self), "Karma",
                [("id%d" % i, mock.Mock()) for i in range(10)])
        self.assertTrue(ok)
        self.assertEqual(["Karma"], built, "the stage was composed more than once")
        self.assertEqual([10], written)
        self.assertEqual(1, len(submitted), "more than one husk for one batch")
        self.assertEqual(10, len(submitted[0].frames))
        net.destroy.assert_called_once()    # under the disabler: a bare destroy returns on Ctrl+Z
        submitted[0].discard()

    def test_a_material_with_no_material_node_is_left_out(self):
        submitted = []
        with mock.patch.object(preview, "build_usd_scaffold",
                               lambda preferences, renderer="Karma": {"net": mock.Mock()}), \
                mock.patch.object(preview, "write_batch",
                                  lambda scaffold, items, out_dir:
                                  {"usd": "u", "prims": ["/m0", "", "/m2"], "ball": "/b",
                                   "renderer": "Karma", "ocio": ("d", "v", "s")}), \
                mock.patch.object(husk_job.jobs, "submit",
                                  lambda job, blocking=False: submitted.append(job)):
            thumbs.ThumbNailRenderer.render_batch(
                test_support.fixture_prefs(self), "Karma",
                [("a", mock.Mock()), ("b", mock.Mock()), ("c", mock.Mock())])
        job = submitted[0]
        self.assertEqual(["a", "c"], [asset_id for asset_id, _png in job.frames])
        self.assertEqual(["/m0", "/m2"], job.batch["prims"])
        job.discard()


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
