"""The Categories model over a real 2.0 library: names, order, colours and counts."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(  # scripts/python: the dev tree, not the install ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category, guard
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


def _write(prefs, document: dict) -> None:
    """The library's materials.json as `document`, written whole."""
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

    def test_display_strips_a_leading_underscore_and_the_sort_role_does_not(self):
        model = self.model()
        self.index.row.return_value = 2
        self.assertEqual("_Hidden", model.data(self.index, role=model.CatSortRole))
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


class NormalizeBracketsItsResetTest(unittest.TestCase):
    """`normalize_categories` brackets its row swap in a reset pair. ▸r/model-contracts"""

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
        """The bracket must not fire when no rows change."""
        model = self._model(["Metal", "Wood"])
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        self.assertEqual(0, model.normalize_categories())
        self.assertEqual([], seen, "a no-op reset the whole model")

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
        for door, edit in (
                ("add", lambda: (model.check_add_category("Zeta"),
                                 model.check_add_category("Alpha"))),
                ("move", lambda: model.move_category(4, 1)),
                ("rename", lambda: model.rename_category("usds", "USD")),
                ("remove", lambda: model.remove_category("Alpha")),
                ("sort", lambda: (model.check_add_category("Aardvark"),
                                  model.sort_categories()))):
            with self.subTest(door=door):
                self.assertEqual(
                    0, self._resets_on_refresh_after(edit),
                    "the refresh reset the sidebar after a local %s" % door)


class TheAllRowHasOneRule(unittest.TestCase):
    """All is shown, never stored as a category, and `category.is_all` alone says so."""

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
        self.assertEqual([], offenders, "the All rule is written again at %s" % offenders)


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
