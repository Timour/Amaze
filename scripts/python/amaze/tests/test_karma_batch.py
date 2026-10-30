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
from amaze.actions import materials as material_actions  # noqa: E402
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
                test_support.plugins_loaded("Octane"), \
                mock.patch.object(nodes.NodeHandler, "import_asset_to_scene", imported), \
                mock.patch.object(nodes.NodeHandler, "cleanup"), \
                mock.patch.object(thumbs.ThumbNailRenderer, "render_batch",
                                  lambda prefs, renderer, items:
                                  batches.append((renderer, len(items)))):
            if len(rows) == 1:
                material_actions.render_thumbnail(model, rows[0])
            else:
                material_actions.render_thumbnails(model, rows)
        return batches

    def test_a_selection_is_one_batch_per_renderer_and_one_render_a_batch_of_one(self):
        """render_thumbnail takes the same path: no second way to render one material."""
        for renderers, batches in ((["MaterialX"] * 10, [("Karma", 10)]),
                                   (["MaterialX", "Octane", "MaterialX", "Octane"],
                                    [("Karma", 2), ("Octane", 2)]),
                                   (["MaterialX"], [("Karma", 1)])):
            with self.subTest(renderers=renderers):
                model = self._model(renderers)
                self.assertEqual(batches, self._batches(model, list(range(len(renderers)))))


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
            material_actions.render_thumbnails(model, [0, 1])
        self.assertEqual(
            [], imported,
            "Update Render imported every row before finding that "
            "nothing can render without a Scene Viewer")
        self.assertEqual([messages.NO_SCENE_VIEWER_FOR_THUMBNAIL], shown,
                         "the batch did not say why, exactly once")


OCIO = {"display": "sRGB - Display", "view": "ACES 1.0 - SDR Video", "space": "ACEScg"}
ABSENT_SETTINGS = "amaze_absent_octane_settings"    # a stage type no category has: createNode refuses


def _viewer_and_husk(testcase):
    """A Scene Viewer's OCIO for both seams, and husk's queue recording instead of rendering."""
    for seam in (preview.thumbnail_scene, preview):
        patcher = mock.patch.object(seam, "ocio_from_viewer", lambda: dict(OCIO))
        patcher.start()
        testcase.addCleanup(patcher.stop)
    submitted = []
    patcher = mock.patch.object(husk_job.jobs, "submit",
                                lambda job, blocking=False: submitted.append(job))
    patcher.start()
    testcase.addCleanup(patcher.stop)
    testcase.addCleanup(lambda: [job.discard() for job in submitted])
    return submitted


class AnOctaneTwinWithoutOctaneIsRefusedNotRaised(unittest.TestCase):
    """Update Render on a Convert-to-Octane twin where Octane is not loaded. ▸r/hou-errors"""

    @classmethod
    def setUpClass(cls):
        if not hou.getenv("OCIO"):    # save_node refuses without one
            hou.putenv("OCIO", "/dev/null")

    def setUp(self):
        from amaze.core import library
        self.submitted = _viewer_and_husk(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library.MaterialLibrary(preferences=self.prefs)
        self.twin = self._octane_twin()

    def _octane_twin(self):
        """A MaterialX builder carrying Octane's mark, saved as Convert to Octane saves one."""
        from amaze.render import nodes
        from amaze.render.material_conversion import octane
        builder = nodes.make_karma_builder(hou.node("/mat"), "octane_twin_probe")
        self.addCleanup(builder.destroy)
        nodes.wire_builder_output(builder, builder.createNode("mtlxstandard_surface"))
        octane.mark(builder)
        held = test_support.asset_ids(self.model)
        self.assertEqual("Octane", material_actions.add_asset(
            self.model, builder, "", "", False, name="Octane Twin Probe"))
        twin, = test_support.arrived(self.model, held)
        return twin

    def test_one_message_names_the_twin_and_the_rest_render(self):
        from amaze.core import renderers
        from amaze.render import nodes
        karma = [row for row, mat in enumerate(self.model.assets)
                 if renderers.is_karma(mat.renderer)][:2]
        self.assertTrue(karma, "premise: the fixture library holds no MaterialX material")
        rows = [self.model.find_asset_row_by_id(self.twin.mat_id)] + karma
        shown, imported = [], []
        desktop = types.SimpleNamespace(paneTabOfType=lambda kind: None)
        ui = types.SimpleNamespace(
            curDesktop=lambda: desktop, paneTabs=lambda: (),
            setStatusMessage=lambda *a, **k: None,
            displayMessage=lambda text, *a, **k: shown.append(text))
        real = nodes.NodeHandler.import_asset_to_scene

        def spy(handler, mat, *args, **kwargs):
            imported.append(mat.name)
            return real(handler, mat, *args, **kwargs)

        with mock.patch.object(hou, "ui", ui, create=True), test_support.plugins_loaded(), \
                mock.patch.object(preview.usd_scene, "OCTANE_SETTINGS", ABSENT_SETTINGS), \
                mock.patch.object(nodes.NodeHandler, "import_asset_to_scene", spy):
            try:
                material_actions.render_thumbnails(self.model, rows)
            except hou.Error as exc:
                self.fail("Update Render raised out of the menu: %s" % exc)
        self.assertEqual(1, len(shown), "not ONE message for the batch: %r" % shown)
        self.assertIn('"%s"' % self.twin.name, shown[0])
        self.assertIn("Octane", shown[0])
        self.assertNotIn(self.twin.name, imported, "the twin was imported before refusing")
        self.assertEqual([len(karma)], [len(job.frames) for job in self.submitted],
                         "the MaterialX materials in the same Update Render did not render")

    def test_a_stage_the_host_refuses_is_a_failed_batch(self):
        material = hou.node("/mat").createNode("subnet", "refused_stage_probe")
        self.addCleanup(material.destroy)
        material.createNode("mtlxstandard_surface")
        before = set(hou.node("/obj").children())
        with mock.patch.object(preview.usd_scene, "OCTANE_SETTINGS", ABSENT_SETTINGS), \
                test_support.captured_log() as log:
            try:
                ok = thumbs.ThumbNailRenderer.render_batch(
                    self.prefs, "Octane", [("REFUSED_STAGE", material)])
            except hou.Error as exc:
                self.fail("the refused stage escaped render_batch: %s" % exc)
        self.assertFalse(ok)
        self.assertEqual([], self.submitted)
        self.assertEqual(before, set(hou.node("/obj").children()), "a half-built stage was left")
        self.assertEqual(1, len([r for r in log.records("exception")
                                 if r["data"].get("renderer") == "Octane"]),
                         "the refusal was not logged with its traceback")


class ASaveAskedNotToRenderRendersNothing(unittest.TestCase):
    """`add_asset(render=False)` skips the per-save thumbnail a batch renders later. ▸r/husk-startup"""

    @classmethod
    def setUpClass(cls):
        if not hou.getenv("OCIO"):
            hou.putenv("OCIO", "/dev/null")

    def test_render_false_skips_the_thumbnail_and_the_default_renders(self):
        from amaze.core import library
        from amaze.render import nodes
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 1
        model = library.MaterialLibrary(preferences=prefs)
        for kwargs, renders in (({"render": False}, 0), ({}, 1)):
            with self.subTest(kwargs=kwargs):
                builder = nodes.make_karma_builder(hou.node("/mat"), "render_flag_probe")
                self.addCleanup(builder.destroy)
                nodes.wire_builder_output(builder, builder.createNode("mtlxstandard_surface"))
                held = test_support.asset_ids(model)
                with mock.patch.object(thumbs.ThumbNailRenderer, "create_thumb_mtlx",
                                       return_value=True) as rendered:
                    self.assertEqual("Karma", material_actions.add_asset(
                        model, builder, "", "", False, **kwargs))
                self.assertEqual(1, len(test_support.arrived(model, held)), "premise: no save")
                self.assertEqual(renders, rendered.call_count)


class ALandedRenderRepaintsItsTile(unittest.TestCase):
    """The panel connects a Material model once; a landed PNG repaints that one tile."""

    def test_one_connection_however_many_panels(self):
        from amaze.core import library
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library.MaterialLibrary(preferences=test_support.fixture_prefs(self))
        if not model.rowCount():
            self.skipTest("the fixture library holds no material")
        painted = []
        with mock.patch.object(model, "_add_thumb_paths", painted.append):
            material_actions.connect(model)
            material_actions.connect(model)    # a second panel on the same library
            self.addCleanup(husk_job.jobs.thumbnailWritten.disconnect,
                            model._on_thumbnail_written)
            husk_job.jobs.thumbnailWritten.emit(str(model.assets[0].mat_id))
        self.assertEqual([0], painted, "a landed render repainted no tile, or one twice")


class UpdateRenderOnMaterialTiles(unittest.TestCase):
    """Update Render on a Material selection is one render batch, through the Material verbs."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        try:
            test_support.stop_panel_workers(cls.panel)
        except Exception:                                 # noqa: BLE001
            pass

    def test_the_selection_goes_in_one_batch(self):
        proxy = self.panel.material_sorted_model
        if proxy.rowCount() < 2:
            self.skipTest("the fixture shows fewer than two materials")
        indexes = [proxy.index(0, 0), proxy.index(1, 0)]
        model = self.panel.material_model
        wanted = [model.assets[proxy.mapToSource(i).row()].mat_id for i in indexes]
        batches = []
        with mock.patch.object(thumbs.ThumbNailRenderer, "render_assets",
                               lambda preferences, mats: batches.append(
                                   [mat.mat_id for mat in mats])):
            self.panel.sections["material"].update_preview(indexes)
        self.assertEqual([wanted], batches)


if __name__ == "__main__":
    unittest.main()
