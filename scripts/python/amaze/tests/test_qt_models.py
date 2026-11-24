"""Qt model contracts: one test per requirement in docs/requirements/qt-models.md."""

import contextlib
import types
import unittest
from unittest import mock

from PySide6 import QtCore, QtWidgets

from amaze.core import category, documents, grid_columns, library_files, material, model_registry
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
MATERIALS = library_files.MATERIALS


class _Models(unittest.TestCase):
    """The fixture library's shared models, as every pane on it gets them."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.models = model_registry.models_for(self.prefs)
        self.model, self.sidebar = self.models["material_model"], self.models["category_model"]

    def key(self, name: str) -> str:
        return next(str(asset.mat_id) for asset in self.model.assets if asset.name == name)

    def row(self, name: str) -> int:
        return self.model.find_asset_row_by_id(self.key(name))


class ModelContractTest(_Models):
    """Requirements on the grid and sidebar models, which crash Houdini when broken."""

    def peer_adds(self, key: str) -> None:
        """Another session saves a new row, which the next save here brings in: an insert."""
        held = documents.Library(self.prefs.dir, "u-peer").document(MATERIALS)
        held.put("assets", key, {"name": key, "categories": [], "tags": []})
        self.assertTrue(held.save(), "premise: the other session's save")

    def test_qm10_no_action_moves_a_row_inside_a_layout_change(self):
        actions = (
            ("a save", lambda: self.model.set_tile_name(self.row("gold"), "Golden")),
            ("an add, as a convert and an import end",
             lambda: self.model.add_saved(material.Material(name="Added"))),
            ("a delete", lambda: self.model.remove_rows([self.row("glass")])),
            ("a drop on a category",
             lambda: category.assign(self.model, self.sidebar, {self.key("Golden")}, "Karma_Mats")),
            ("a rename", lambda: category.rename(self.model, self.sidebar, ["usds"], "Shiny")),
            ("a removal", lambda: category.remove(self.model, self.sidebar, ["Shiny"])),
            ("a sort", lambda: (self.sidebar.check_add_category("Aaa"),
                                self.sidebar.sort_categories())))
        for number, (what, action) in enumerate(actions):
            self.peer_adds("P%d" % number)
            with test_support.row_moves_inside_a_layout_change(self.model, self.sidebar) as caught:
                action()
            self.assertEqual([], caught, what)
            self.assertIn("P%d" % number, test_support.asset_ids(self.model),
                          "%s: premise, the other session's row came in" % what)

    def test_qm11_a_change_that_replaces_every_row_is_one_reset_closed_even_when_it_fails(self):
        self.sidebar.check_add_category("Aaa")
        resets = []
        for model in (self.model, self.sidebar):
            model.modelAboutToBeReset.connect(lambda: resets.append("open"))
            model.modelReset.connect(lambda: resets.append("closed"))
        for what, change, fault in (
                ("a sort", self.sidebar.sort_categories, None),
                ("a switch", self.model.switch_model_data, None),
                ("a sidebar switch", self.sidebar.switch_model_data, None),
                ("a failed switch", self.model.switch_model_data,
                 mock.patch.object(self.model, "_read_rows", side_effect=OSError("cut"))),
                ("a failed sidebar switch", self.sidebar.switch_model_data,
                 mock.patch.object(category, "stored_order", side_effect=OSError("cut")))):
            del resets[:]
            with fault or contextlib.nullcontext(), contextlib.suppress(OSError):
                change()
            self.assertEqual(["open", "closed"], resets, what)

    def test_qm12_no_view_uses_an_index_from_a_model_since_reset_or_replaced(self):
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(self.sidebar)
        selection = QtCore.QItemSelectionModel(proxy)
        current = QtCore.QItemSelectionModel.SelectionFlag.NoUpdate
        selection.setCurrentIndex(proxy.index(2, 0), current)
        live = grid_columns.live_current_index(selection)
        self.assertEqual("usds", live.data(category.SIDEBAR_KEY_ROLE), "premise: a live index")
        self.sidebar.switch_model_data()
        self.assertIsNone(grid_columns.live_current_index(selection), "kept across a reset")
        replaced, other = proxy.index(1, 0), category.CategoriesSidebarProxy()
        other.setSourceModel(self.sidebar)
        held = self.sidebar.index(2, 0)
        self.sidebar.remove_category("usds")
        for model, index in ((other, replaced), (self.sidebar, held)):
            shown = types.SimpleNamespace(model=lambda model=model: model,
                                          currentIndex=lambda index=index: index)
            self.assertIsNone(grid_columns.live_current_index(shown), type(model).__name__)


class PaneTest(_Models):
    """A pane engine as the QML pane builds one, with no window."""

    def pane(self):
        from amaze.core import matx_sources
        from amaze.pane import asks, pane as pane_mod
        with mock.patch.object(matx_sources, "_request", side_effect=OSError("no network")):
            built = pane_mod.Pane(mock.Mock(spec=asks.Asks))
            built.prefs = self.prefs
            built.library.setup()
        self.addCleanup(test_support.dispose_panel, built)
        self.addCleanup(test_support.stop_panel_workers, types.SimpleNamespace(pane=built))
        return built

    def connected(self) -> dict:
        """{(model, signal): how many connections} of the shared models' signals."""
        found = {}
        for attr, model in self.models.items():
            meta = model.metaObject()
            for method in map(meta.method, range(meta.methodCount())):
                if method.methodType() == QtCore.QMetaMethod.MethodType.Signal:
                    signal = bytes(method.methodSignature()).decode()
                    found[attr, signal] = model.receivers(QtCore.SIGNAL(signal))
        return found

    def test_qm13_a_closed_pane_leaves_nothing_connected_and_nothing_scheduled(self):
        self.pane()
        alone = self.connected()
        second = self.pane()
        self.assertNotEqual(alone, self.connected(), "premise: the second pane is connected")
        test_support.stop_panel_workers(types.SimpleNamespace(pane=second))
        second.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()
        self.assertEqual({}, {key: count for key, count in self.connected().items()
                              if count != alone[key]}, "left connected by the closed pane")
        self.assertTrue(self.model.set_tile_name(self.row("gold"), "Golden"),
                        "a change after the close reached the closed pane's save timer")


if __name__ == "__main__":
    unittest.main()
