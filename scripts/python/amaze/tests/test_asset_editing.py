"""Asset editing: one test per requirement in docs/requirements/asset-editing.md."""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # the first app picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402

from amaze import messages
from amaze.core import category, code_library, debug, gradient_library, library, library_db
from amaze.core import library_files, locations, material, sidebar_model
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
MATERIALS = library_files.MATERIALS


class _Edits(unittest.TestCase):
    """The fixture library's materials and their sidebar; every save is written at once."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.model = library.MaterialLibrary(self.prefs)
        self.sidebar = category.Categories(self.prefs)

    def key(self, name: str) -> str:
        return next(str(asset.mat_id) for asset in self.model.assets if asset.name == name)

    def row(self, name: str) -> int:
        return self.model.find_asset_row_by_id(self.key(name))

    def field(self, name: str, which: str):
        return getattr(self.model.assets[self.row(name)], which)

    def on_disk(self) -> dict:
        library_db.flush(self.prefs)
        with open(os.path.join(self.prefs.dir, MATERIALS), encoding="utf-8") as handle:
            return json.load(handle)


class AssetEditingTest(_Edits):
    """Requirements on editing assets in the grid and the sidebar."""

    def test_ed10_an_edit_star_icon_or_delete_acts_on_exactly_the_tiles_chosen(self):
        chosen = {self.key("gold"), self.key("glass")}
        self.assertEqual(1, self.model.remove_rows([self.row("glass")]))    # gone since chosen
        self.model.set_tile_name(self.row("plastic"), "Aaa")    # rows move: it now sorts first
        self.assertTrue(self.model.edit_tiles(chosen, category="Picked"))
        gold = self.row("gold")
        self.model.toggle_favs([gold, -1, self.model.rowCount()])
        self.assertEqual(1, self.model.set_tile_icons([gold, -1], {"face": "generic"}))
        self.assertEqual(0, self.model.remove_rows([-1, self.model.rowCount()]))
        picked = [a.name for a in self.model.assets if a.categories == ["Picked"]]
        starred = [a.name for a in self.model.assets
                   if locations.is_favourite(self.prefs, a.mat_id, MATERIALS)]
        faced = [a.name for row, a in enumerate(self.model.assets) if self.model.tile_icon(row)]
        self.assertEqual((["gold"], ["gold"], ["gold"], 6),
                         (picked, starred, faced, self.model.rowCount()))

    def test_ed20_a_rename_to_a_blank_or_unchanged_name_changes_nothing(self):
        row = self.row("gold")
        with mock.patch.object(self.model, "save", wraps=self.model.save) as saves:
            for name in ("", "   ", "gold", " gold "):
                self.assertFalse(self.model.set_tile_name(row, name), repr(name))
            self.assertTrue(self.model.edit_tiles({self.key("gold")}, name="  "))
        self.assertEqual((0, "gold"), (saves.call_count, self.model.assets[row].name))

    def test_ed21_tags_keep_their_order_with_no_blanks_or_repeats(self):
        gold, glass = self.key("gold"), self.key("glass")
        self.model.edit_tiles({gold}, tags=" rough, , metal,rough ")
        self.model.edit_tiles({glass}, tags="metal")
        self.model.edit_tiles({gold, glass}, tags="metal, new")
        self.assertEqual((["rough", "metal", "new"], ["metal", "new"]),
                         (self.field("gold", "tags"), self.field("glass", "tags")))
        self.model.edit_tiles({gold}, tags="")
        self.assertEqual(([], ["metal", "new"]), (self.on_disk()["assets"][gold]["tags"],
                                                  self.on_disk()["assets"][glass]["tags"]))
        self.assertEqual([], material.Material.from_dict({"tags": ["", " "]}).tags)

    def test_ed22_an_asset_has_one_category_and_a_mixed_field_keeps_each_own(self):
        two = {self.key("gold"), self.key("Bricks")}
        self.model.edit_tiles(two, name="One", tags="x", category="")
        self.assertEqual((["usds"], ["Karma_Mats"], "gold"), (
            self.field("gold", "categories"), self.field("Bricks", "categories"),
            self.model.assets[self.row("gold")].name))
        self.model.edit_tiles(two, category="Red, Brick")
        self.assertEqual([["Red, Brick"]] * 2, [self.field(name, "categories")
                                                 for name in ("gold", "Bricks")])
        self.assertEqual(["A"], material.Material.from_dict({"categories": ["A", "B"]}).categories)

    def test_ed23_renaming_a_category_renames_it_everywhere_and_onto_a_name_merges(self):
        usds = [a.mat_id for a in self.model.assets if a.categories == ["usds"]]
        self.sidebar.set_color("usds", "#ff8000")
        self.assertEqual("Shiny", category.rename(self.model, self.sidebar, ["usds"], "Shiny"))
        self.assertEqual(([["Shiny"]] * len(usds), ["Karma_Mats", "Shiny"], "#ff8000"), (
            [self.model.assets[self.model.find_asset_row_by_id(i)].categories for i in usds],
            self.sidebar.top_keys(), self.sidebar.color_of("Shiny")))
        self.sidebar.check_add_category("_WIP")
        self.assertEqual("_WIP", category.rename(self.model, self.sidebar,
                                                 ["Shiny", "Karma_Mats"], "WIP"))
        self.assertEqual("", category.rename(self.model, self.sidebar, ["_WIP"], "All"))
        self.assertEqual((["_WIP"], {"_WIP"}), (self.sidebar.top_keys(), {
            name for row in self.on_disk()["assets"].values() for name in row["categories"]}))

    def test_ed24_removing_a_category_takes_it_off_every_asset_and_drops_its_colour(self):
        self.sidebar.set_color("usds", "#ff8000")
        rows = self.model.rowCount()
        self.assertTrue(category.remove(self.model, self.sidebar, ["usds"]))
        saved = self.on_disk()
        self.assertEqual((rows, ["Karma_Mats"], ""), (
            len(saved["assets"]), list(saved["categories"]), self.sidebar.color_of("usds")))
        self.assertNotIn(["usds"], [row["categories"] for row in saved["assets"].values()])

    def drop(self, proxy, key: str, row: int) -> None:
        """The sidebar row keyed `key` dragged between rows, before shown row `row`."""
        data = QtCore.QMimeData()
        data.setData(sidebar_model.MOVE_MIME, key.encode("utf-8"))
        proxy.dropMimeData(data, QtCore.Qt.DropAction.MoveAction, row, 0, QtCore.QModelIndex())

    def test_ed25_the_sidebar_keeps_its_dragged_or_sorted_order_and_a_refused_move_goes_back(self):
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(self.sidebar)
        self.sidebar.check_add_category("_WIP")
        self.drop(proxy, "_WIP", 1)
        test_support.reset_database_singletons()
        self.assertEqual(["_WIP", "Karma_Mats", "usds"], category.Categories(self.prefs).top_keys())
        self.sidebar.sort_categories()
        self.assertEqual(["All", "Karma_Mats", "usds", "WIP"],
                         [proxy.index(row, 0).data() for row in range(proxy.rowCount())])
        self.prefs.library_user = ""
        with mock.patch.object(debug, "refuse"):
            self.drop(proxy, "_WIP", 1)
        self.assertEqual(["Karma_Mats", "usds", "_WIP"], self.sidebar.top_keys())

    def test_ed26_a_categorys_colour_is_kept_with_the_library_and_shows_on_its_tiles(self):
        self.sidebar.set_color("usds", "#4af2a1")
        shown = {self.model.index(row, 0).data(self.model.CategoryColorRole)
                 for row, asset in enumerate(self.model.assets) if asset.categories == ["usds"]}
        self.assertEqual(({"#4af2a1"}, "#4af2a1"),
                         (shown, self.on_disk()["categories"]["usds"]["color"]))

    def test_ed27_a_tiles_face_is_kept_in_its_database_only(self):
        before = test_support.library_state(self.prefs.dir)
        self.assertEqual(0, self.model.set_tile_icons([self.row("gold")], {"face": "generic"}))
        self.assertEqual(0, self.model.set_tile_icons([self.row("glass")],
                                                      {"name": "layers", "bg": "#4af2a1"}))
        self.on_disk()
        after = test_support.library_state(self.prefs.dir)
        self.assertEqual([MATERIALS], [path for path in set(before) | set(after)
                                       if before.get(path) != after.get(path)])
        test_support.reset_database_singletons()
        fresh = library.MaterialLibrary(self.prefs)
        gold, glass = (fresh.find_asset_row_by_id(self.key(name)) for name in ("gold", "glass"))
        self.assertEqual(("generic", "layers"), (fresh.tile_icon(gold).get("face"),
                                                 fresh.tile_icon(glass).get("name")))
        library_db.document(self.prefs, MATERIALS).put("icons", self.key("glass"), {"name": 5})
        self.assertEqual({}, fresh.tile_icon(glass))

    def test_ed28_customize_writes_one_save_for_the_whole_selection(self):
        keys = {self.key(name) for name in ("gold", "glass", "Bricks")}
        with mock.patch.object(self.model, "save", wraps=self.model.save) as saves:
            self.model.edit_tiles(keys, tags="probe", category="Shelf")
            self.model.edit_tiles(keys, tags="probe", category="Shelf")
        self.assertEqual(1, saves.call_count)

    def test_ed29_an_edit_the_library_refuses_is_not_shown_as_done_and_the_user_is_told(self):
        gold, code = self.key("gold"), code_library.CodeLibrary(self.prefs)
        snippet = code.add_snippet("print(1)", "Loop", "Python", "", "")
        gestures = (
            lambda: self.model.edit_tiles({gold}, name="Other", tags="t", category="C"),
            lambda: category.rename(self.model, self.sidebar, ["usds"], "Shiny"),
            lambda: category.remove(self.model, self.sidebar, ["usds"]),
            lambda: category.assign(self.model, self.sidebar, {gold}, "Karma_Mats"),
            lambda: self.sidebar.check_add_category("New"),
            lambda: self.sidebar.set_color("usds", "#ff0000"),
            lambda: self.model.toggle_favs([self.row("gold")]),
            lambda: code.save_from_editor(snippet, "print(2)", "Spin", "Python", "", ""))

        def shown():
            return ([asset.get_as_dict() for asset in self.model.assets + code.assets],
                    self.sidebar.top_keys(), dict(self.sidebar.colors()),
                    locations.is_favourite(self.prefs, gold, MATERIALS))
        before, self.prefs.library_user = shown(), ""
        with mock.patch.object(debug, "refuse") as told:
            for gesture in gestures:
                gesture()
        self.assertEqual(before, shown())
        self.assertEqual([messages.NO_USER_PICKED] * len(gestures),
                         [call.args[0] for call in told.call_args_list])
        self.prefs.library_user = test_support.FIXTURE_USER
        test_support.put(self.prefs.dir, MATERIALS, b"{ ruined")
        with mock.patch.object(debug, "refuse") as told, mock.patch.object(debug, "alert"):
            library_db.refresh(self.prefs)
            self.assertFalse(self.model.edit_tiles({gold}, name="Other"))
        self.assertEqual(messages.CHANGE_REFUSED_READ_ONLY % "Materials", told.call_args.args[0])

    def test_ed30_the_shipped_snippets_and_palettes_are_added_once_and_only_when_taken(self):
        for model, sidebar, seed in (
                (code_library.CodeLibrary, code_library.CodeCategories, "seed_starter_snippets"),
                (gradient_library.GradientLibrary, gradient_library.GradientCategories,
                 "seed_curated_palettes")):
            model, sidebar = model(self.prefs), sidebar(self.prefs)
            self.prefs.library_user = ""
            self.assertEqual((0, 0), (getattr(model, seed)(sidebar), model.rowCount()), seed)
            self.prefs.library_user = test_support.FIXTURE_USER
            added = getattr(model, seed)(sidebar)
            self.assertGreater(added, 0, seed)
            self.assertEqual((0, added), (getattr(model, seed)(sidebar), model.rowCount()), seed)
            self.assertEqual(added, len(library_db.guard_of(self.prefs).read(
                model.DB_FILENAME).document["assets"]), seed)


if __name__ == "__main__":
    unittest.main()
