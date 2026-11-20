"""The Categories model over a real 2.0 library: names, order, colours and counts."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

from PySide6 import QtCore

sys.path.insert(  # scripts/python: the dev tree, not the install ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category, guard
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


def _write(prefs, document: dict) -> None:
    """Write `document` as the library's materials.json, replacing the file."""
    with open(os.path.join(prefs.dir, "materials.json"), "w", encoding="utf-8") as handle:
        handle.write(guard.encode(document).decode("utf-8"))


class TestCategories(unittest.TestCase):
    """The sidebar model reads its names in their order, All first, and saves them back."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = self.prefs_for()
        self.index = MagicMock()

    def prefs_for(self):
        prefs = test_support.fixture_prefs(self)
        test_support.with_fixture_user(prefs.dir)
        _write(prefs, {"categories": {"Cat1": {"order": 0}, "_Hidden": {"order": 1},
                                      "Cat2": {"order": 2}},
                       "assets": {}})
        return prefs

    def model(self):
        return category.Categories(self.prefs)

    def test_init_reads_the_names_in_order_with_all_first(self):
        model = self.model()
        self.assertIs(self.prefs, model.preferences)
        self.assertEqual(["_All", "Cat1", "_Hidden", "Cat2"], model._categories)
        self.assertEqual(4, model.rowCount())

    def test_display_strips_a_leading_underscore_and_the_key_role_does_not(self):
        model = self.model()
        self.index.row.return_value = 2
        self.assertEqual("_Hidden", model.data(self.index, role=category.SIDEBAR_KEY_ROLE))
        self.assertEqual("Hidden", model.data(self.index, role=0))
        self.index.row.return_value = 1
        self.assertEqual("Cat1", model.data(self.index, role=0))

    def test_a_junk_row_does_not_abort_the_counts(self):
        _write(self.prefs, {"categories": {"Cat1": {"order": 0}},
                            "assets": {"a": {"categories": ["Cat1"], "renderer": "Karma"},
                                       "b": "junk left by a hand edit",
                                       "c": {"categories": ["Cat1"], "renderer": "Karma"}}})
        model = self.model()
        self.assertEqual(2, model._category_count("Cat1"))
        self.assertEqual(2, model._category_count("_All"))

    def test_a_name_holding_a_comma_counts_as_one(self):
        _write(self.prefs, {"categories": {"Wood, Oak": {"order": 0}},
                            "assets": {"a": {"categories": ["Wood, Oak"], "renderer": "Karma"},
                                       "b": {"categories": "Wood, Oak", "renderer": "Karma"}}})
        model = self.model()
        self.assertEqual((2, 0), (model._category_count("Wood, Oak"), model._category_count("Wood")),
                         "the count split a category name at its comma")

    def test_remove_and_rename_save_and_the_database_holds_it(self):
        model = self.model()
        model.remove_category("Cat1")
        model.rename_category("Cat2", "Second")
        test_support.reset_database_singletons()
        self.assertEqual(["_All", "_Hidden", "Second"], self.model()._categories)

    def test_a_rename_to_nothing_known_still_saves(self):
        model = self.model()
        model.save = MagicMock()
        original = list(model._categories)
        model.rename_category("NonExistent", "NewName")
        self.assertEqual(original, model._categories)
        model.save.assert_called_once()

    def test_check_add_category_adds_only_new_trimmed_names_and_saves_only_then(self):
        cases = (  # (typed, names that must appear, whether a save follows)
            ("Multiple Values...", (), False),
            ("NewCat", ("NewCat",), True),
            ("Cat1", (), False),
            ("Wood, Oak", ("Wood, Oak",), True),    # a comma is part of the one name
            ("  SpacedCat  ", ("SpacedCat",), True),
            ("   ", (), False),
        )
        for typed, added, saves in cases:
            with self.subTest(typed=typed):
                model = self.model()
                model.save = MagicMock()
                before = list(model._categories)
                model.check_add_category(typed)
                self.assertEqual(sorted(before + list(added)), sorted(model._categories))
                self.assertEqual(saves, model.save.called)

    def test_the_order_and_a_colour_are_what_is_saved(self):
        model = self.model()
        model.move_category(3, 1)
        model.set_color("Cat1", "#ff0000")
        with open(os.path.join(self.prefs.dir, "materials.json"), encoding="utf-8") as handle:
            stored = json.load(handle)["categories"]
        self.assertEqual({"Cat2": 0, "Cat1": 1, "_Hidden": 2},
                         {name: entry["order"] for name, entry in stored.items()})
        self.assertEqual("#ff0000", stored["Cat1"]["color"])
        self.assertNotIn("_All", stored, "All is a view, never stored")

    def test_the_proxy_finds_a_row_by_its_stored_name_and_not_a_hidden_one(self):
        """`index_of` maps a shown row through the proxy; a hidden or unknown key gives no row."""
        _write(self.prefs, {"categories": {"Cat1": {"order": 0}, "_Hidden": {"order": 1}},
                            "assets": {"a": {"categories": ["_Hidden"], "renderer": "Karma"}}})
        model = self.model()
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        model.set_renderer_filter("karma")    # Cat1 holds no Karma asset, so the proxy hides it
        proxy.invalidateFilter()
        self.assertEqual(["All", "Hidden"], [proxy.index(row, 0).data() for row in range(proxy.rowCount())],
                         "premise: the proxy does not hide the empty category")
        self.assertEqual(proxy.index(0, 0), proxy.index_of(""))
        self.assertEqual(proxy.index(1, 0), proxy.index_of("_Hidden"))
        self.assertEqual("_Hidden", proxy.index_of("_Hidden").data(category.SIDEBAR_KEY_ROLE))
        self.assertTrue(model.index_of("Cat1").isValid(), "premise: Cat1 is a row of the list")
        self.assertFalse(proxy.index_of("Cat1").isValid(), "a hidden row was given as shown")
        self.assertFalse(proxy.index_of("Hidden").isValid(), "a displayed name found a row")
        self.assertFalse(proxy.index_of("Nothing").isValid())

    def test_the_key_role_is_the_one_stored_name(self):
        """No second role for the stored name: the key role gives it below All, "" on All."""
        model = self.model()
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        proxy.hide_empty = False
        for holder in (model, proxy):
            self.assertFalse(hasattr(holder, "CatSortRole"),
                             "%s still defines a second stored-name role" % type(holder).__name__)
        self.assertIsNone(model.data(model.index(2, 0), int(QtCore.Qt.ItemDataRole.UserRole)),
                          "the list still answers a stored-name role beside SIDEBAR_KEY_ROLE")
        self.assertEqual(["", "Cat1", "_Hidden", "Cat2"],
                         [proxy.index(row, 0).data(category.SIDEBAR_KEY_ROLE)
                          for row in range(proxy.rowCount())])

    def test_the_proxy_refresh_recounts_and_refilters(self):
        """A category that loses its asset hides and one that gains one shows, on one call."""
        _write(self.prefs, {"categories": {"Cat1": {"order": 0}, "Cat2": {"order": 1}},
                            "assets": {"a": {"categories": ["Cat1"], "renderer": "Karma"}}})
        model = self.model()
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        model.set_renderer_filter("karma")
        proxy.invalidateFilter()

        def shown():
            return [proxy.index(row, 0).data(category.SIDEBAR_KEY_ROLE)
                    for row in range(proxy.rowCount())]

        self.assertEqual(["", "Cat1"], shown(), "premise: the empty Cat2 is not hidden")
        held = model._doc()
        self.assertTrue(held.drop("assets", "a"), "premise: the asset was not dropped")
        self.assertTrue(held.put("assets", "b", {"categories": ["Cat2"], "renderer": "Karma"}),
                        "premise: the asset was not added")
        self.assertEqual(["", "Cat1"], shown(), "premise: the counts were not cached")
        proxy.refresh()
        self.assertEqual(["", "Cat2"], shown(),
                         "the refresh kept the old counts or did not refilter")


class NormalizeEmitsAResetPairTest(unittest.TestCase):
    """`normalize_categories` emits a reset pair around replacing its rows. ▸r/model-contracts"""

    def _model(self, entries):
        from amaze.core import category as category_mod
        from amaze.tests import test_support
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        model = category_mod.Categories(preferences=prefs)
        model._categories = list(entries)
        return model

    def test_it_emits_a_matched_reset_pair(self):
        model = self._model(["Metal", "metal ", "", "Wood", "Metal"])
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        model.modelReset.connect(lambda: seen.append("done"))
        changed = model.normalize_categories()
        self.assertGreater(changed, 0, "the fixture needed no cleaning")
        self.assertEqual(
            ["about", "done"], seen,
            "the row set was replaced without a matched reset pair")

    def test_a_clean_list_resets_nothing(self):
        """No reset is emitted when no rows change."""
        model = self._model(["Metal", "Wood"])
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        self.assertEqual(0, model.normalize_categories())
        self.assertEqual([], seen, "a call that changed nothing reset the whole model")

class ALocalEditIsNotReadAsAMerge(unittest.TestCase):
    """A refresh resets the sidebar for a change made elsewhere, never for one of its own edits."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        test_support.with_fixture_user(self.prefs.dir)
        self.model = category.Categories(preferences=self.prefs)
        self.resets = []
        self.model.modelReset.connect(lambda: self.resets.append(True))

    def _resets_on_refresh_after(self, edit):
        edit()
        del self.resets[:]
        self.model.apply_refresh()
        return len(self.resets)

    def test_a_category_added_here_keeps_the_selection(self):
        from PySide6 import QtCore
        selection = QtCore.QItemSelectionModel(self.model)
        selection.select(self.model.index(1, 0),
                         QtCore.QItemSelectionModel.SelectionFlag.Select)
        resets = self._resets_on_refresh_after(
            lambda: self.model.check_add_category("Added Here"))
        self.assertEqual(
            (0, True), (resets, selection.isSelected(self.model.index(1, 0))),
            "the refresh read the sidebar's own edit as a merge, reset it "
            "and dropped the selection")

    def test_no_local_edit_is_read_as_a_merge(self):
        model = self.model
        for verb, edit in (
                ("add", lambda: (model.check_add_category("Zeta"),
                                 model.check_add_category("Alpha"))),
                ("move", lambda: model.move_category(4, 1)),
                ("rename", lambda: model.rename_category("usds", "USD")),
                ("remove", lambda: model.remove_category("Alpha")),
                ("sort", lambda: (model.check_add_category("Aardvark"),
                                  model.sort_categories()))):
            with self.subTest(verb=verb):
                self.assertEqual(
                    0, self._resets_on_refresh_after(edit),
                    "the refresh reset the sidebar after a local %s" % verb)


class TheAllRowHasOneRule(unittest.TestCase):
    """All is shown, never stored as a category, and only `category.is_all` decides that."""

    def test_both_spellings_and_nothing_else(self):
        for name, want in (("_All", True), ("All", True), ("", False), (None, False),
                           ("_WIP", False), ("all", False), ("All Metals", False)):
            with self.subTest(name=name):
                self.assertIs(want, category.is_all(name))

    def test_no_other_module_spells_the_pair(self):
        import ast
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        home = os.path.join(root, "core", "category.py")
        offenders = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in sorted(files):
                path = os.path.join(folder, name)
                if not name.endswith(".py") or path == home:
                    continue
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                        continue
                    words = {e.value for e in node.elts if isinstance(e, ast.Constant)}
                    if {"All", "_All"} <= words:
                        offenders.append("%s:%d" % (os.path.relpath(path, root), node.lineno))
        self.assertEqual([], offenders, "the All pair is spelled outside category.py at %s" % offenders)


class TheFixtureRowCountTest(unittest.TestCase):

    def _fixture_categories(self):
        test_support.reset_database_singletons()
        model = category.Categories(preferences=test_support.fixture_prefs(self))
        self.addCleanup(test_support.reset_database_singletons)
        return model

    def test_a_removal_and_an_addition_move_the_row_count(self):
        """The fixture has _All/Karma_Mats/usds; one removed leaves two, one added makes four."""
        for why, change, rows in (
                ("as loaded", lambda model: None, 3),
                ("usds removed", lambda model: model.remove_category("usds"), 2),
                ("one added",
                 lambda model: model.check_add_category("brand_new_cat"), 4)):
            with self.subTest(why):
                cat_model = self._fixture_categories()
                change(cat_model)
                self.assertEqual(cat_model.rowCount(), rows)


if __name__ == "__main__":
    unittest.main()
