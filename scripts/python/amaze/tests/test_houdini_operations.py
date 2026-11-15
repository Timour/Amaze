"""Imports and saves run inside Houdini's interruptable operation ▸p/amaze-follows-houdini"""

import inspect
import os
import shutil
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

import hou  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.panel import panel as panel_mod  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.panel import online_import, package_import  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the log


class _Recording:
    """A stand-in for hou.InterruptableOperation that records every progress report."""

    opened = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.reports = []
        _Recording.opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def updateLongProgress(self, fraction, text):
        self.reports.append((round(fraction, 3), text))

    def updateProgress(self, fraction=-1.0):
        self.reports.append((round(fraction, 3), ""))


class _EscOnTheThirdReport(_Recording):
    """The user's Esc, on the third progress report."""

    def updateLongProgress(self, fraction, text):
        super().updateLongProgress(fraction, text)
        if len(self.reports) == 3:
            raise hou.OperationInterrupted()


class _EscOnTheSecondReport(_Recording):
    """The user's Esc, on the second progress report."""

    def updateLongProgress(self, fraction, text):
        super().updateLongProgress(fraction, text)
        if len(self.reports) == 2:
            raise hou.OperationInterrupted()


def _record(title):
    return types.SimpleNamespace(title=title, kind="material", source="test")


class _OnThePanel(unittest.TestCase):
    """A fixture panel with a status line the test can read."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        _Recording.opened.clear()
        self.said = []
        ui = types.SimpleNamespace(
            setStatusMessage=lambda text, *a, **k: self.said.append(text),
            displayMessage=lambda *a, **k: 0)
        patcher = mock.patch.object(hou, "ui", ui, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class TheOnlineImportRunsInsideHoudinisOperation(_OnThePanel):

    def _import(self, titles, operation):
        imported = []

        def one(record, on_progress=None, renderer=None, render=True):
            on_progress(0.5)
            on_progress(1.0)
            imported.append(record.title)
            return True, ""

        with mock.patch.object(hou, "InterruptableOperation", operation), \
                mock.patch.object(self.panel.online_import, "import_material", side_effect=one), \
                mock.patch.object(self.panel, "render_landed"):
            self.panel.online_import.import_records([_record(t) for t in titles])
        return imported

    def test_the_batch_reports_each_record_by_name_and_share(self):
        imported = self._import(["Bricks", "Moss"], _Recording)
        self.assertEqual(["Bricks", "Moss"], imported)
        self.assertEqual(1, len(_Recording.opened),
                         "the batch opened no operation, or more than one")
        self.assertEqual(
            [(0.25, "1/2  Bricks"), (0.5, "1/2  Bricks"),
             (0.75, "2/2  Moss"), (1.0, "2/2  Moss")],
            _Recording.opened[0].reports)

    def test_an_esc_stops_the_batch_after_the_current_record_and_says_so(self):
        imported = self._import(["Bricks", "Moss", "Rust"], _EscOnTheThirdReport)
        self.assertEqual(["Bricks"], imported,
                         "the Esc did not stop the batch after the record in hand")
        self.assertIn(messages.ONLINE_IMPORT_STOPPED % (1, 3), self.said[-1])


class TheSceneImportRunsInsideHoudinisOperation(_OnThePanel):

    def test_an_esc_stops_the_batch_after_the_current_record_and_says_so(self):
        from amaze.core import matx_import
        from amaze.render import nodes
        built = []

        def build(rec, source, resolution, destination, prefs, progress=None, renderer=None):
            progress(1.0)
            builder = hou.node("/mat").createNode("subnet", "esc_probe_" + rec.title)
            self.addCleanup(test_support.drop_node, builder)
            built.append(rec.title)
            return builder, ""

        with mock.patch.object(hou, "InterruptableOperation", _EscOnTheSecondReport), \
                mock.patch.object(nodes, "karma_destination", return_value=hou.node("/mat")), \
                mock.patch.object(self.panel.online_import, "source_for",
                                  return_value=("source", None, "")), \
                mock.patch.object(matx_import, "build_in_scene", side_effect=build):
            self.panel.online_import.import_records_to_scene([_record("Bricks"), _record("Moss")])
        self.assertEqual(["Bricks"], built,
                         "the Esc did not stop the scene import after the record in hand")
        self.assertIn(messages.ONLINE_IMPORT_STOPPED % (1, 2), self.said[-1])


class TheMultiMaterialSaveRunsInsideHoudinisOperation(_OnThePanel):

    def _save(self, names, operation):
        saved = []

        def add(model, node, categories, tags, fav, name=None):
            saved.append(node.name())
            return "Karma"

        picked = []
        for name in names:
            node = hou.node("/mat").createNode("subnet", "save_probe_" + name)
            self.addCleanup(test_support.drop_node, node)
            picked.append(node)
        dialog = types.SimpleNamespace(categories="", tags="", fav=False, name="")
        with mock.patch.object(hou, "InterruptableOperation", operation), \
                mock.patch.object(panel_mod.material_actions, "add_asset", side_effect=add), \
                mock.patch.object(self.panel, "enable_renderer_on_add"), \
                mock.patch.object(self.panel, "update_renderer_toggles"), \
                mock.patch.object(self.panel, "refresh_sidebar_categories"):
            self.panel.sections["material"].commit_save(picked, picked[0], dialog)
        return saved

    def test_each_material_is_reported_by_name_before_its_save(self):
        saved = self._save(["a", "b"], _Recording)
        self.assertEqual(["save_probe_a", "save_probe_b"], saved)
        self.assertEqual(1, len(_Recording.opened))
        self.assertEqual([(0.0, "1/2  save_probe_a"), (0.5, "2/2  save_probe_b")],
                         _Recording.opened[0].reports)

    def test_an_esc_stops_the_batch_after_the_current_material_and_says_so(self):
        saved = self._save(["a", "b", "c"], _EscOnTheSecondReport)
        self.assertEqual(["save_probe_a"], saved,
                         "the Esc did not stop the save after the material in hand")
        self.assertIn(messages.SAVE_STOPPED % (1, 3), self.said[-1])


class AnEscInsideOneRecordReachesTheBatch(_OnThePanel):
    """The Esc raised inside a download leaves the record's own handler for the batch loop."""

    class _Interrupting:
        """A source whose every download is stopped by the Esc."""

        def fetch(self, *args, **kwargs):
            raise hou.OperationInterrupted()

        def import_reader(self, *args, **kwargs):
            raise hou.OperationInterrupted()

    def _prefs(self):
        """Prefs naming a throwaway library folder, removed after the test."""
        folder = test_support.scratch_dir("amaze_esc_")
        self.addCleanup(shutil.rmtree, folder, True)
        return types.SimpleNamespace(dir=folder)

    def _record(self, kind, payload="https://example.invalid/p.zip"):
        return types.SimpleNamespace(title="Bricks", kind=kind, source="test", uid="1",
                                     payload=payload)

    def test_an_esc_in_a_measurement_download_is_not_a_failed_record(self):
        from amaze.core import matx_import
        prefs = self._prefs()
        with self.assertRaises(hou.OperationInterrupted,
                               msg="the Esc in a measurement download became a failed record"):
            matx_import._producer_for(self._record("values"), self._Interrupting(), None, prefs)

    def test_an_esc_in_a_package_download_is_not_a_download_failed(self):
        from amaze.core import matx_import
        prefs = self._prefs()
        with self.assertRaises(hou.OperationInterrupted,
                               msg="the Esc in a package download became a Download failed"):
            matx_import._producer_for(self._record("material"), self._Interrupting(), "1k", prefs)

    def test_an_esc_in_a_store_package_download_is_not_a_failed_tile(self):
        record = self._record("package", payload={"package": "https://example.invalid/p.amazepkg",
                                                  "entry": {"type": "asset"}})
        with self.assertRaises(hou.OperationInterrupted,
                               msg="the Esc in a store package download became a failed tile"):
            self.panel.package_import.import_record(record, self._Interrupting(), restore=True)


class ThePanelPumpsNothingForImportsAndSaves(unittest.TestCase):
    """The import and save paths leave the event loop to Houdini's operation."""

    def test_no_processEvents_in_the_import_and_save_paths(self):
        for owner, name in ((online_import.OnlineImport, "download_operation"),
                            (online_import.OnlineImport, "import_records"),
                            (package_import.PackageImport, "restore"),
                            (online_import.OnlineImport, "import_records_to_scene"),
                            (panel_mod.AmazePanel, "save_asset")):
            source = inspect.getsource(getattr(owner, name))
            self.assertNotIn("processEvents", source,
                             owner.__name__ + "." + name + " pumps the event loop itself")
        self.assertNotIn("processEvents",
                         inspect.getsource(sections.MaterialSection.commit_save),
                         "MaterialSection.commit_save pumps the event loop itself")


if __name__ == "__main__":
    unittest.main()
