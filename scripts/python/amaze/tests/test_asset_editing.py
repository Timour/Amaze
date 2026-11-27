"""Asset editing: one test per requirement in docs/requirements/asset-editing.md."""

import json
import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # the first app picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from amaze import messages
from amaze.core import category, code_library, debug, documents, gradient_library, library, library_db
from amaze.core import grid_columns, library_files, locations, material, sidebar_model
from amaze.pane import asks, customize
from amaze.tests import test_support

try:    # without Houdini the Name window's and the palette menu's tests skip
    import hou
    from amaze.dialogs import name_window
    from amaze.pane import menus
    from amaze.qml import pane as qml_pane
    from amaze.sections import color as color_section
except ImportError:
    hou = None

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

    def cat(self, name: str) -> str:
        """The key of the category named `name`, made when there is none."""
        return self.sidebar.check_add_category(name)

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
        picked = self.cat("Picked")
        self.assertTrue(self.model.edit_tiles(chosen, category=picked))
        gold = self.row("gold")
        self.model.toggle_favs([gold, -1, self.model.rowCount()])
        self.assertEqual(1, self.model.set_tile_icons([gold, -1], {"face": "generic"}))
        self.assertEqual(0, self.model.remove_rows([-1, self.model.rowCount()]))
        picked = [a.name for a in self.model.assets if a.categories == [picked]]
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
        self.assertEqual(([self.cat("usds")], [self.cat("Karma_Mats")], "gold"), (
            self.field("gold", "categories"), self.field("Bricks", "categories"),
            self.model.assets[self.row("gold")].name))
        red = self.cat("Red, Brick")
        self.model.edit_tiles(two, category=red)
        self.assertEqual(([[red]] * 2, "Red, Brick"), (
            [self.field(name, "categories") for name in ("gold", "Bricks")],
            self.sidebar.name_of(red)))
        self.assertEqual(["A"], material.Material.from_dict({"categories": ["A", "B"]}).categories)

    def test_ed23_renaming_a_category_changes_only_its_name_and_onto_a_used_name_joins(self):
        usds, karma = self.cat("usds"), self.cat("Karma_Mats")
        members = [a.mat_id for a in self.model.assets if a.categories == [usds]]
        self.sidebar.set_color(usds, "#ff8000")
        self.assertEqual(usds, category.rename(self.model, self.sidebar, [usds], "Shiny"))
        saved, column = self.on_disk(), grid_columns.KEYS.index("category")
        self.assertEqual(([[usds]] * len(members), [karma, usds], "#ff8000", "Shiny", "Shiny"), (
            [saved["assets"][key]["categories"] for key in members], self.sidebar.top_keys(),
            saved["categories"][usds]["color"], saved["categories"][usds]["name"],
            self.model.index(self.row("gold"), column).data()))
        self.assertEqual(karma, category.rename(self.model, self.sidebar, [usds], "karma_mats"))
        saved = self.on_disk()
        self.assertEqual(([karma], {karma}, "Karma_Mats", "#ff8000"), (
            self.sidebar.top_keys(), {key for row in saved["assets"].values()
                                      for key in row["categories"]},
            saved["categories"][karma]["name"], self.sidebar.color_of(karma)))

    def test_ed24_removing_a_category_takes_it_off_every_asset_and_drops_its_colour(self):
        usds, karma = self.cat("usds"), self.cat("Karma_Mats")
        self.sidebar.set_color(usds, "#ff8000")
        rows = self.model.rowCount()
        self.assertTrue(category.remove(self.model, self.sidebar, [usds]))
        saved = self.on_disk()
        self.assertEqual((rows, [karma], ""), (
            len(saved["assets"]), list(saved["categories"]), self.sidebar.color_of(usds)))
        self.assertNotIn([usds], [row["categories"] for row in saved["assets"].values()])

    def drop(self, proxy, key: str, row: int) -> None:
        """The sidebar row keyed `key` dragged between rows, before shown row `row`."""
        data = QtCore.QMimeData()
        data.setData(sidebar_model.MOVE_MIME, key.encode("utf-8"))
        proxy.dropMimeData(data, QtCore.Qt.DropAction.MoveAction, row, 0, QtCore.QModelIndex())

    def test_ed25_the_sidebar_keeps_its_dragged_or_sorted_order_and_a_refused_move_goes_back(self):
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(self.sidebar)
        proxy.hide_empty = False    # the order is tested: the new, empty category must show
        karma, usds, wip = self.cat("Karma_Mats"), self.cat("usds"), self.cat("_WIP")
        self.drop(proxy, wip, 1)
        test_support.reset_database_singletons()
        self.assertEqual([wip, karma, usds], category.Categories(self.prefs).top_keys())
        self.sidebar.sort_categories()
        self.assertEqual(["All", "Karma_Mats", "usds", "WIP"],
                         [proxy.index(row, 0).data() for row in range(proxy.rowCount())])
        self.prefs.library_user = ""
        with mock.patch.object(debug, "refuse"):
            self.drop(proxy, wip, 1)
        self.assertEqual([karma, usds, wip], self.sidebar.top_keys())

    def test_ed26_a_categorys_colour_is_kept_with_the_library_and_shows_on_its_tiles(self):
        usds = self.cat("usds")
        self.sidebar.set_color(usds, "#4af2a1")
        shown = {self.model.index(row, 0).data(self.model.CategoryColorRole)
                 for row, asset in enumerate(self.model.assets) if asset.categories == [usds]}
        self.assertEqual(({"#4af2a1"}, "#4af2a1"),
                         (shown, self.on_disk()["categories"][usds]["color"]))

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
        keys, shelf = {self.key(name) for name in ("gold", "glass", "Bricks")}, self.cat("Shelf")
        window = customize.Customize(
            asks.CustomizeQuestion(icon={}, stroke=0.0, tile_name="", tile_name_enabled=False,
                                   tile_tags="", categories=self.sidebar.choices(), tile_category="",
                                   face="image", faces={}, can_preview=True),
            lambda answer: self.model.edit_tiles(keys, answer.name, answer.tags, answer.category),
            ask_colour=None)
        with mock.patch.object(self.model, "save", wraps=self.model.save) as saves:
            applied = window.commit("Other", "probe", shelf)
            accepted = window.commit("Other", "probe", shelf)
        self.assertEqual((1, (None, "probe", shelf), (None, None, None)),
                         (saves.call_count, applied[1:], accepted[1:]))

    def test_ed29_an_edit_the_library_refuses_is_not_shown_as_done_and_the_user_is_told(self):
        gold, code = self.key("gold"), code_library.CodeLibrary(self.prefs)
        snippet = code.add_snippet("print(1)", "Loop", "Python", "", "")
        usds, karma = self.cat("usds"), self.cat("Karma_Mats")
        gestures = (
            lambda: self.model.edit_tiles({gold}, name="Other", tags="t", category=karma),
            lambda: category.rename(self.model, self.sidebar, [usds], "Shiny"),
            lambda: category.remove(self.model, self.sidebar, [usds]),
            lambda: category.assign(self.model, self.sidebar, {gold}, karma),
            lambda: self.sidebar.check_add_category("New"),
            lambda: self.sidebar.set_color(usds, "#ff0000"),
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

    def test_ed32_a_section_never_gets_two_categories_of_one_name(self):
        usds, wood = self.cat("usds"), self.cat("Wood")
        self.assertEqual([usds, usds, wood, wood, ""], [self.sidebar.check_add_category(name)
                                                        for name in ("usds", "USDS", "wood",
                                                                     " Wood ", "All")])
        code = code_library.CodeLibrary(self.prefs)
        sidebar = code_library.CodeCategories(self.prefs)
        loops = sidebar.check_add_category("Loops")
        snippet = code.add_snippet("print(1)", "Loop", "Python",
                                   sidebar.check_add_category("loops"), "")
        self.assertEqual(([loops], [(loops, "Loops")]), (
            code.assets[code.find_asset_row_by_id(snippet)].categories, sidebar.choices()))
        self.assertEqual(["Karma_Mats", "usds", "Wood"],
                         sorted((entry["name"] for entry in self.on_disk()["categories"].values()),
                                key=str.lower))

    def test_ed33_same_named_categories_from_a_sync_are_asked_about_once_an_open(self):
        theirs, also = "f" * 32, "e" * 32
        other = documents.Library(self.prefs.dir, "u-other").document(MATERIALS)
        other.put(category.SECTION, theirs, {"name": "wood", "order": 0})
        other.put(category.SECTION, also, {"name": "karma_mats", "order": 99})
        self.assertTrue(other.save())
        mine, karma = self.cat("Wood"), self.cat("Karma_Mats")    # this save merges the other's two in
        self.sidebar.apply_refresh()
        self.model.edit_tiles([self.key("gold")], category=mine)
        asked = []

        def answer(reply):
            return lambda name, count, apart: asked.append((name, count, apart)) or reply.get(name, "")
        for _time in range(2):    # Esc on both; the second pass asks nothing
            category.settle_names(self.model, self.sidebar, answer({}))
        self.assertEqual([("Karma_Mats", 2, ["Karma_Mats 2"]), ("wood", 2, ["wood 2"])], asked)
        self.assertLessEqual({theirs, also, mine, karma}, set(self.sidebar.top_keys()), "Esc changed it")
        self.sidebar.switch_model_data()    # the next open asks again
        category.settle_names(self.model, self.sidebar, answer(
            {"wood": category.JOIN, "Karma_Mats": category.KEEP_BOTH}))
        saved = self.on_disk()
        self.assertEqual((["Karma_Mats", "Karma_Mats 2", "wood"], [theirs]), (
            sorted(entry["name"] for key, entry in saved["categories"].items()
                   if key in (theirs, also, mine, karma)),
            saved["assets"][self.key("gold")]["categories"]))

    def test_ed35_a_category_renamed_two_ways_is_asked_about_once_where_it_is_noticed(self):
        wood, stone = self.cat("Wood"), self.cat("Stone")
        self.model.save()    # nothing of this session's waits: a rename's own save is the one that merges
        for key, theirs, mine in ((wood, "Timber", "Oak"), (stone, "Rock", "Slate")):
            other = documents.Library(self.prefs.dir, "u-other").document(MATERIALS)
            other.edit(category.SECTION, key, name=theirs)
            self.assertTrue(other.save())
            category.rename(self.model, self.sidebar, [key], mine)    # saved second: renamed two ways
        self.sidebar.apply_refresh()
        asked = []
        for _time in range(2):    # the second pass asks nothing
            category.settle_renames(self.model, self.sidebar, lambda mine, theirs, by: asked.append(
                (mine, theirs, by)) or theirs == "Rock")
        self.assertEqual([("Oak", "Timber", "u-other"), ("Slate", "Rock", "u-other")], asked)
        saved = self.on_disk()["categories"]
        self.assertEqual(("Oak", "Rock"), (saved[wood]["name"], saved[stone]["name"]))

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


@unittest.skipUnless(hou, "Houdini is not loaded")
class PaletteInterpolationTest(_Edits):
    """A palette of mixed curves and the Interpolation rows of its tile menu."""

    def test_ed34_interpolation_puts_every_key_on_the_curve_picked_in_one_save(self):
        palettes = gradient_library.GradientLibrary(self.prefs)
        ramp = {"keys": [0.0, 0.3, 1.0], "values": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "bases": ["Linear", "Constant", "Linear"]}
        palettes.add_user_gradient("Dusk", "", ramp)
        key = next(str(asset.mat_id) for asset in palettes.assets if asset.name == "Dusk")
        colors = palettes.entry(palettes.find_asset_row_by_id(key))["colors"]
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(palettes)
        section = color_section.GradientSection(types.SimpleNamespace(gradient_model=palettes,
                                                                      gradient_sorted_model=proxy))
        entry, = [entry for entry in section.GRID_MENU if entry.label == "Interpolation"]

        def menu() -> tuple:
            """The palette's Interpolation rows: (the menu, {curve: row key}, the curves checked)."""
            index = proxy.mapFromSource(palettes.index(palettes.find_asset_row_by_id(key), 0))
            opened = menus.Menu(section, (entry,), [index], index)
            rows = opened.rows[0]["rows"]
            curve = {row["key"]: opened.runs[row["key"]][1][0] for row in rows}
            return opened, {curve[row["key"]]: row["key"] for row in rows}, [
                curve[row["key"]] for row in rows if row.get("checked")]
        opened, keys, checked = menu()
        self.assertEqual([], checked, "a curve is checked on a palette of mixed curves")
        with mock.patch.object(palettes, "save", wraps=palettes.save) as saves:
            opened.run(keys["CatmullRom"])
        library_db.flush(self.prefs)
        stored = library_db.guard_of(self.prefs).read(palettes.DB_FILENAME).document["assets"][key]
        self.assertEqual((1, dict(ramp, bases=["CatmullRom"] * 3), colors),
                         (saves.call_count, stored["ramp"], stored["colors"]))
        self.assertEqual(["CatmullRom"], menu()[2])


def _key(window, key, text="") -> None:
    """One press and release of `key` in `window`, typing `text`."""
    for kind in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease):
        QtCore.QCoreApplication.sendEvent(
            window, QtGui.QKeyEvent(kind, key, QtCore.Qt.KeyboardModifier.NoModifier, text))


def _click(window, label: str) -> None:
    """A left click on the window's button that reads `label`."""
    items = [window.contentItem()]
    while items:
        item = items.pop()
        if item.metaObject().className().startswith("Button") and item.property("text") == label:
            centre = item.mapToScene(QtCore.QPointF(item.width() / 2, item.height() / 2)).toPoint()
            QtTest.QTest.mouseClick(window, QtCore.Qt.MouseButton.LeftButton,
                                    QtCore.Qt.KeyboardModifier.NoModifier, centre)
            return
        items.extend(item.childItems())
    raise AssertionError("the window has no %s button" % label)


@unittest.skipUnless(hou, "Houdini is not loaded")
class NameWindowTest(unittest.TestCase):
    """The QML pane's Name window, which its menus' Add, Rename, New Folder and Save Scene open."""

    def answer(self, host, end) -> list:
        """What the window, opened on `Warm` as the menus open it, hands on when `end(window)` ends it."""
        answers = []
        host.ask_name("Add Category", "Warm", answers.append)
        window = next(shown for shown in QtGui.QGuiApplication.topLevelWindows()
                      if isinstance(shown, name_window.NameWindow) and shown.isVisible())
        self.assertTrue(test_support.pump_until(lambda: window.activeFocusItem() is not None))
        end(window)
        test_support.pump_until(lambda: answers, 3.0)
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        return answers

    def test_ed31_ok_or_return_uses_the_name_typed_and_cancel_esc_or_a_close_does_nothing(self):
        host = qml_pane.PaneState()
        self.addCleanup(host.deleteLater)
        self.assertTrue(asks.answers(host, "ask_name"), "the QML pane's menus cannot ask for a name")
        key = QtCore.Qt.Key

        def typed(window):
            _key(window, key.Key_End)
            for letter in "er":
                _key(window, key(ord(letter.upper())), letter)
            _key(window, key.Key_Return)

        def cleared(window):
            for _ in "Warm":
                _key(window, key.Key_Backspace)
            _key(window, key.Key_Return)

        ends = (typed, lambda window: _click(window, "OK"), cleared,
                lambda window: _click(window, "Cancel"), lambda window: _key(window, key.Key_Escape),
                lambda window: window.close())
        self.assertEqual([["Warmer"], ["Warm"], [""], [None], [None], [None]],
                         [self.answer(host, end) for end in ends])


if __name__ == "__main__":
    unittest.main()
