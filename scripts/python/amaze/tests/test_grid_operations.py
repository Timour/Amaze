"""The Grid area's operations: each verb is one Section method that is handed the selection."""

import ast
import contextlib
import json
import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import messages  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.actions import nodes as node_actions  # noqa: E402
from amaze.core import library_policy, matx_import, renderers, tile_icons  # noqa: E402
from amaze.dialogs import base_dialog, code_dialog  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.render import nodes as render_nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def menu_verbs_calling(*attributes):
    """Every `menu_*` verb in sections.py that calls one of these methods, as name:line."""
    with open(os.path.join(PACKAGE, "panel", "sections.py"),
              encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    verbs = [node for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef)
             and node.name.startswith("menu_")]
    assert verbs, "no menu verbs found to check - the scan is vacuous"
    offenders = []
    for verb in verbs:
        for call in ast.walk(verb):
            if (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in attributes):
                offenders.append("%s:%d" % (verb.name, call.lineno))
    return offenders


class EveryContextOwnsTheVerbsItOffers(unittest.TestCase):

    def test_a_context_with_no_tiles_answers_harmlessly(self):
        """Online rows have no favourite state, so the verb is a no-op there, never an error."""
        context = sections.OnlineContext.__new__(sections.OnlineContext)
        self.assertFalse(sections.OnlineContext.takes_favourites)
        context.toggle_favourite([])          # must not raise


class OnlyASectionThatRENDERSOffersUpdatePreview(unittest.TestCase):
    """Update Render only where a preview is rendered (Materials, Nodes), never derived (Code, Color)."""

    def test_only_a_section_that_renders_puts_it_in_a_menu(self):
        """The flag says who can re-render, the menu gate reads it, and File asks the selection."""
        for name, renders, in_menu in (("MaterialSection", True, True),
                                       ("CopSection", True, True),
                                       ("FileSection", True, False),
                                       ("CodeSection", False, False),
                                       ("GradientSection", False, False)):
            with self.subTest(context=name):
                context = getattr(sections, name)
                self.assertEqual(
                    renders, bool(context.offers_preview_update),
                    "%s is wrong about whether it can re-render" % name)
                if renders:
                    self.assertTrue(callable(
                        getattr(context, "update_preview", None)))
                self.assertEqual(
                    in_menu, bool(self._preview_gate(name)),
                    "%s's menu is wrong about Update Render for an empty "
                    "selection" % name)

    def _preview_gate(self, name):
        """Update Render is one row of the shared tail, so the row's `shown` gate is what decides."""
        entry = next(e for e in sections.GRID_MENU_TAIL
                     if e.label == "Update Render")
        self.assertTrue(
            entry.shown,
            "Update Render is unconditional in the shared tail, so "
            "every section offers it whatever it can do")
        context = getattr(sections, name)(None)  # a panel-less instance: the gate reads the section, and False for an absent model
        return getattr(context, entry.shown)([], None)


class DeleteIsONEShapeWithFourSetsOfWORDS(unittest.TestCase):
    """Delete counts distinct rows, asks, removes highest row first, then refreshes the sidebar."""

    DELETING = ("MaterialSection", "CopSection", "CodeSection",   # Delete removes a library record; File has no Delete, its rows are files
                "GradientSection")

    def test_the_FILE_section_offers_no_delete_at_all(self):
        """A File row is a file on disk; the section browses locations and owns nothing in them."""
        self.assertFalse(sections.FileSection.deletes_rows)

    def test_each_context_says_what_deleting_COSTS(self):
        for name in self.DELETING:
            with self.subTest(context=name):
                context = getattr(sections, name)
                for count in (1, 4):
                    prompt = context.delete_prompt(count)
                    self.assertTrue(
                        prompt, "%s has no wording for deleting %d"
                        % (name, count))
                    self.assertIn(
                        "Delete", prompt,
                        "%s's prompt does not say what it does" % name)
                self.assertNotEqual(
                    context.delete_prompt(1), context.delete_prompt(4),
                    "%s asks the same question for one row and four - "
                    "'the selected material(s)' never told anyone how "
                    "many" % name)
                self.assertIn(
                    "4", context.delete_prompt(4),
                    "%s does not say HOW MANY" % name)
        prompts = {getattr(sections, name).delete_prompt(1)
                   for name in self.DELETING}
        self.assertEqual(
            len(self.DELETING), len(prompts),
            "the sections share a delete sentence, so at least two are "
            "telling the user about the wrong thing")

    def test_only_COLOR_quotes_the_palette_by_NAME(self):
        """A palette is picked by its label; the others take the name and leave it out."""
        prompt = sections.GradientSection.delete_prompt(1, "Sunset")
        self.assertIn('"Sunset"', prompt)
        self.assertIn("gradient goes for good", prompt)
        for name in ("MaterialSection", "CopSection", "CodeSection"):
            with self.subTest(context=name):
                context = getattr(sections, name)
                self.assertEqual(context.delete_prompt(1),
                                 context.delete_prompt(1, "Sunset"))


class TheCUSTOMIZEDialogSurvivesAModelRESET(unittest.TestCase):
    """A model reset voids every persistent index, so tiles are found by `tile_key(row)` identity."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _open_on(self, model, row):
        self.panel.edit_tile_icon(model, None, [model.index(row, 0)])
        dialog = self.panel._icon_dialog
        self.assertIsNotNone(dialog, "the dialog did not open")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _ok(self, dialog):
        dialog.canceled = False
        dialog.spec = {"name": "star", "color": "#4af2a1"}
        dialog.finished.emit(1)
        QtWidgets.QApplication.processEvents()

    def test_a_RESET_that_moves_nothing_or_REORDERS_still_finds_the_asset(self):
        """The case row numbers get wrong and identity does not."""
        model = self.panel.material_model
        self.assertGreater(model.rowCount(), 2, "need three assets")

        def bare():
            model.beginResetModel()    # every row stays put, and every held index dies anyway
            model.endResetModel()

        def reordering():
            model.beginResetModel()
            model.assets.reverse()
            model.endResetModel()

        for why, row, reset in (("a bare reset", 1, bare),
                                ("a reordering reset", 2, reordering)):
            with self.subTest(why):
                target = str(model.assets[row].mat_id)
                bystander = str(model.assets[0].mat_id)
                dialog = self._open_on(model, row)
                reset()
                QtWidgets.QApplication.processEvents()
                self._ok(dialog)
                by_id = {str(a.mat_id): r for r, a in enumerate(model.assets)}
                self.assertIn(target, by_id, "the asset vanished")
                self.assertTrue(
                    model.tile_icon(by_id[target]),
                    "the icon was dropped: a model reset killed the held "
                    "indexes and the dialog had nothing left to apply to")
                self.assertFalse(
                    model.tile_icon(by_id[bystander]),
                    "the icon landed on a different asset - the rows were "
                    "re-ordered under the open dialog")

    def test_every_tile_model_says_what_its_rows_are_KEYED_by(self):
        """The three families, one question: an id, a path or a uid, without the panel knowing which."""
        for attr in ("material_model", "cop_model", "code_model",
                     "file_files_model", "gradient_model"):
            with self.subTest(model=attr):
                model = getattr(self.panel, attr, None)
                self.assertIsNotNone(model, "%s is missing" % attr)
                self.assertTrue(
                    callable(getattr(model, "tile_key", None)),
                    "%s cannot say what its rows are keyed by" % attr)
                if model.rowCount():
                    key = model.tile_key(0)
                    self.assertTrue(
                        key, "%s answered an empty key for row 0, which "
                        "every row would share" % attr)
                    self.assertEqual(
                        "", model.tile_key(model.rowCount() + 5),
                        "%s answers a key for a row that does not exist"
                        % attr)


class NoMENUKnowsHowToFavourite(unittest.TestCase):
    """No menu verb favourites, deletes or relayouts rows itself, read from the source."""

    def test_no_right_click_handler_favourites_or_deletes_rows_itself(self):
        offenders = menu_verbs_calling("toggle_fav", "toggle_favorite",
                                       "remove_asset")
        self.assertEqual(
            [], offenders,
            "a right-click verb still favourites or removes rows itself, "
            "at %s - which is where the repaint and the highest-row-first "
            "rule have to be remembered" % offenders)

    def test_no_layout_change_is_opened_or_closed_by_hand(self):
        """A model's begin/end contract or ui_helpers.relayout(); a bare layoutChanged segfaults H21."""
        def emits(name, menu_verbs_only, signal):
            with open(os.path.join(PACKAGE, "panel", name),
                      encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            scopes = [tree]
            if menu_verbs_only:
                scopes = [node for node in ast.walk(tree)
                          if isinstance(node, ast.FunctionDef)
                          and node.name.startswith("menu_")]
                self.assertTrue(scopes, "no menu verbs found to check")
            return ["%s:%d" % (name, call.lineno)
                    for scope in scopes for call in ast.walk(scope)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and isinstance(call.func.value, ast.Attribute)
                    and signal(call)]

        for why, name, menu_verbs_only, signal in (
                ("a right-click verb opens or closes one", "sections.py", True,
                 lambda call: call.func.value.attr.startswith("layout")),
                ("panel.py opens one", "panel.py", False,
                 lambda call: call.func.value.attr == "layoutAboutToBeChanged"),
                ("panel.py emits a bare layoutChanged", "panel.py", False,
                 lambda call: not call.args
                 and call.func.value.attr == "layoutChanged"),
                ("online_import.py opens one", "online_import.py", False,
                 lambda call: call.func.value.attr == "layoutAboutToBeChanged"),
                ("online_import.py emits a bare layoutChanged", "online_import.py", False,
                 lambda call: not call.args
                 and call.func.value.attr == "layoutChanged"),
                ("package_import.py opens one", "package_import.py", False,
                 lambda call: call.func.value.attr == "layoutAboutToBeChanged"),
                ("package_import.py emits a bare layoutChanged", "package_import.py", False,
                 lambda call: not call.args
                 and call.func.value.attr == "layoutChanged"),
                ("drop_placement.py opens one", "drop_placement.py", False,
                 lambda call: call.func.value.attr == "layoutAboutToBeChanged"),
                ("drop_placement.py emits a bare layoutChanged", "drop_placement.py", False,
                 lambda call: not call.args
                 and call.func.value.attr == "layoutChanged"),
                ("tile_capture.py opens one", "tile_capture.py", False,
                 lambda call: call.func.value.attr == "layoutAboutToBeChanged"),
                ("tile_capture.py emits a bare layoutChanged", "tile_capture.py", False,
                 lambda call: not call.args
                 and call.func.value.attr == "layoutChanged")):
            with self.subTest(why):
                self.assertEqual([], emits(name, menu_verbs_only, signal),
                                 "%s by hand - use ui_helpers.relayout(), "
                                 "which closes it in a finally" % why)


class FavouritingWorksInEverySection(unittest.TestCase):
    """Through the real panel and models, the verb flips the star in all three archetypes."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _first_row(self, key, displaced=False):
        """`displaced` filters to the last row, so proxy 0 is another source row and catches a mix-up."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        self.assertIsNotNone(proxy, "the %s tab has no grid" % key)
        self.assertGreater(proxy.rowCount(), 0,
                           "the %s fixture is empty, so this test "
                           "cannot say anything" % key)
        context = panel.active_section()
        if displaced:
            self.assertGreater(
                proxy.rowCount(), 1,
                "the %s fixture has one row, so nothing can be "
                "displaced" % key)
            context.filter_text(proxy.index(proxy.rowCount() - 1, 0).data())
            self.addCleanup(self._clear_filter, key)
            QtWidgets.QApplication.processEvents()
            proxy = panel.thumblist.model()
            self.assertGreater(proxy.rowCount(), 0, "the filter left none")
            self.assertNotEqual(
                0, proxy.mapToSource(proxy.index(0, 0)).row(),
                "the surviving row is source row 0 too, so a verb "
                "acting on the proxy row would still be right here")
        return context, proxy, proxy.index(0, 0)

    def _clear_filter(self, key):
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        self.panel.active_section().filter_text("")
        QtWidgets.QApplication.processEvents()

    def _favourite_role(self, panel, key):
        model = panel.thumblist.model().sourceModel()
        return model.FavoriteRole

    def test_the_verb_flips_the_star_in_each_section(self):
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, proxy, index = self._first_row(key, displaced=True)
                role = self._favourite_role(self.panel, key)
                before = bool(index.data(role))

                context.toggle_favourite([index])
                QtWidgets.QApplication.processEvents()

                self.assertEqual(
                    not before, bool(proxy.index(0, 0).data(role)),
                    "%s's favourite did not change" % key)

                context.toggle_favourite([proxy.index(0, 0)])
                QtWidgets.QApplication.processEvents()
                self.assertEqual(before,
                                 bool(proxy.index(0, 0).data(role)),
                                 "%s's favourite did not toggle back" % key)

    def test_the_PANEL_hands_the_verb_to_whichever_context_is_showing(self):
        """The entry point every menu calls, checked outside Materials so it cannot assume that model."""
        _context, proxy, index = self._first_row("gradient")
        role = self._favourite_role(self.panel, "gradient")
        before = bool(index.data(role))

        self.panel.grid_toggle_favourite([index])
        QtWidgets.QApplication.processEvents()

        self.assertEqual(
            not before, bool(proxy.index(0, 0).data(role)),
            "the panel's verb did nothing in Color - it is still "
            "acting on one section by name")
        self.panel.grid_toggle_favourite([proxy.index(0, 0)])
        QtWidgets.QApplication.processEvents()

    def test_unfavouriting_LEAVES_a_favourites_only_grid(self):
        """With Favourites-only on, un-favouriting a tile takes it out of the grid."""
        for key in ("file", "gradient"):
            with self.subTest(section=key):
                context, proxy, index = self._first_row(key)
                role = self._favourite_role(self.panel, key)
                if not index.data(role):
                    context.toggle_favourite([index])
                    QtWidgets.QApplication.processEvents()

                context.filter_favorites(True)
                self.addCleanup(context.filter_favorites, False)
                QtWidgets.QApplication.processEvents()
                before = proxy.rowCount()
                self.assertGreater(before, 0,
                                   "%s shows nothing with favourites "
                                   "on, so this cannot test the "
                                   "removal" % key)

                context.toggle_favourite([proxy.index(0, 0)])
                QtWidgets.QApplication.processEvents()

                self.assertEqual(
                    before - 1, proxy.rowCount(),
                    "the un-favourited tile is still in a favourites-"
                    "only %s grid" % key)


class AStarOverASelectionWritesOnce(unittest.TestCase):
    """One star gesture over many tiles commits the favourites store once and saves settings once."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _gesture(self, key):
        from amaze.helpers import hostos
        from amaze.prefs import prefs as prefs_mod
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        context = self.panel.active_section()
        proxy = self.panel.thumblist.model()
        rows = range(min(proxy.rowCount(), 5))
        self.assertGreater(len(rows), 1, "premise: %s shows two tiles" % key)
        context.toggle_favourite([proxy.index(0, 0)])    # a first star migrates
        context.toggle_favourite([proxy.index(0, 0)])
        QtWidgets.QApplication.processEvents()
        role = proxy.sourceModel().FavoriteRole
        before = [bool(proxy.index(r, 0).data(role)) for r in rows]
        writes, saves = [], []
        real_write = hostos.write_json_atomic

        def counted(path, *args, **kwargs):
            if os.path.basename(path) == "favourites.json":
                writes.append(path)
            return real_write(path, *args, **kwargs)

        with mock.patch.object(hostos, "write_json_atomic", counted), \
                mock.patch.object(prefs_mod.Prefs, "save",
                                  lambda *_a, **_k: saves.append(1)):
            context.toggle_favourite([proxy.index(r, 0) for r in rows])
        QtWidgets.QApplication.processEvents()
        after = [bool(proxy.index(r, 0).data(role)) for r in rows]
        return before, after, len(writes), len(saves)

    def test_each_section_writes_a_selection_s_stars_once(self):
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                before, after, writes, saves = self._gesture(key)
                self.assertEqual([not star for star in before], after,
                                 "%s did not flip every tile" % key)
                self.assertEqual(1, writes, "%s wrote favourites.json %d "
                                 "times for one gesture" % (key, writes))
                self.assertEqual(1, saves, "%s saved settings %d times "
                                 "for one gesture" % (key, saves))


class ANonModalDialogHoldsIDENTITYNotRowNumbers(unittest.TestCase):
    """Customize is non-modal, so the library can move under it; OK applies to the tile, not a row."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.assertGreater(self.model.rowCount(), 2,
                           "need three materials to shift a row")

    def _open_for(self, row):
        index = self.model.index(row, 0)
        self.panel.edit_tile_icon(self.model, None, [index])
        dialog = self.panel._icon_dialog
        self.assertIsNotNone(dialog, "the dialog did not open")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_single_selection_opens_showing_that_tile_s_own_tags(self):
        """Through the panel's door, not the dialog's constructor: a tagged tile opens with its tags."""
        self.model.set_tile_tags(2, "granite, polished")
        dialog = self._open_for(2)
        self.assertEqual("granite, polished", dialog.tags_edit.text(),
                         "a tagged tile opened with an EMPTY Tags field")

    def test_the_icon_lands_on_the_asset_that_was_SELECTED(self):
        target_id = str(self.model.assets[2].mat_id)
        bystander_id = str(self.model.assets[1].mat_id)
        dialog = self._open_for(2)

        # The library moves under the open dialog.
        self.model.removeRow(0)
        QtWidgets.QApplication.processEvents()

        dialog.canceled = False
        dialog.spec = {"name": "star", "color": "#4af2a1"}
        dialog.finished.emit(1)
        QtWidgets.QApplication.processEvents()

        by_id = {str(a.mat_id): row
                 for row, a in enumerate(self.model.assets)}
        self.assertIn(target_id, by_id, "the target asset is gone")
        self.assertTrue(
            self.model.tile_icon(by_id[target_id]),
            "the asset that was selected has no custom icon - the "
            "dialog applied to a stale row number")
        self.assertFalse(
            self.model.tile_icon(by_id[bystander_id]),
            "the icon landed on a DIFFERENT asset, which is the defect: "
            "the rows shifted under a non-modal dialog")

    def test_a_selection_that_is_GONE_applies_to_nothing(self):
        """Deleting the tile being customised leaves the choice no subject; no other asset is painted."""
        dialog = self._open_for(1)
        survivor_ids = [str(a.mat_id) for a in self.model.assets]
        del survivor_ids[1]

        self.model.removeRow(1)
        QtWidgets.QApplication.processEvents()

        dialog.canceled = False
        dialog.spec = {"name": "star", "color": "#4af2a1"}
        dialog.finished.emit(1)
        QtWidgets.QApplication.processEvents()

        painted = [str(a.mat_id) for row, a in enumerate(self.model.assets)
                   if self.model.tile_icon(row)]
        self.assertEqual(
            [], painted,
            "the icon was applied to %s, none of which is the asset "
            "that was selected" % painted)


class TheStarBadgeClickActsOnTheSELECTION(unittest.TestCase):
    """The star flips the whole selection if its tile is selected, else just its own tile."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.proxy = self.panel.material_sorted_model
        self.role = self.panel.material_model.FavoriteRole
        self.selmodel = self.panel.material_selection_model
        self.assertGreater(self.proxy.rowCount(), 2,
                           "need three materials to tell selection "
                           "semantics apart")

    def _fav(self, row):
        return bool(self.proxy.index(row, 0).data(self.role))

    def _select(self, *rows):
        self.selmodel.clearSelection()
        for row in rows:
            self.selmodel.select(
                self.proxy.index(row, 0),
                QtCore.QItemSelectionModel.SelectionFlag.Select)

    def test_a_click_flips_the_selection_it_is_INSIDE_or_only_its_own_tile(self):
        for why, selected, clicked, flipped in (
                ("inside the selection", (0, 1), 1, (0, 1)),
                ("outside the selection", (0,), 2, (2,))):
            with self.subTest(why):
                rows = sorted(set(selected) | {clicked})
                before = {row: self._fav(row) for row in rows}
                self._select(*selected)
                self.panel.thumb_delegate._badge_clicks["favourite"](
                    self.proxy.index(clicked, 0))
                QtWidgets.QApplication.processEvents()
                self.assertEqual(
                    {row: before[row] != (row in flipped) for row in rows},
                    {row: self._fav(row) for row in rows},
                    "a star clicked %s flipped the wrong tiles" % why)

    def test_which_delegates_offer_the_star_and_comment_clicks(self):
        """Every LOCAL grid wires the star, the online one none; every drawn comment badge is wired."""
        for name in ("thumb_delegate", "asset_delegate",
                     "file_delegate", "gradient_delegate"):
            self.assertIn(
                "favourite", getattr(self.panel, name)._badge_clicks,
                "%s offers no star button" % name)
        self.assertNotIn(
            "favourite", self.panel.matx_delegate._badge_clicks,
            "the online grid grew a star button it cannot serve")
        self.assertIn("versions", self.panel.thumb_delegate._badge_clicks)
        self.assertNotIn(
            "versions", self.panel.asset_delegate._badge_clicks,
            "Node/Code wired the versions click their sections cannot "
            "serve")
        drawn = [d for d in self.panel.tile_delegates()
                 if "comment" in d.badges()]
        self.assertTrue(
            drawn, "no delegate draws a comment badge, so this proves "
                   "nothing")
        for delegate in drawn:
            self.assertIn(
                "comment", delegate._badge_clicks,
                "a delegate reads the notes role but wires no comment "
                "click, so the badge paints and hovers dead")


def _karma_material(test, name):
    """A real Karma material in /mat - what a conversion or an import hands add_asset."""
    node = hou.node("/mat").createNode("subnet", name)
    node.createNode("mtlxstandard_surface", "surf")
    test.addCleanup(node.destroy)
    return node


class NoRowMovesInsideALayoutChange(unittest.TestCase):
    """A row insert inside a layout-change pair segfaults H21 (research.md, measured 2026-08-04)."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 0
        self.model = self.panel.material_model
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()

    def _select(self, row):
        proxy = self.panel.material_sorted_model
        self.panel.material_selection_model.select(
            proxy.mapFromSource(self.model.index(row, 0)),
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _peer_adds_a_row(self, model, row):
        """Another machine writes a row; OUR next save adopts it, which is an INSERT."""
        self.assertTrue(model.save(), "premise: the baseline save failed")
        path = os.path.join(self.panel.prefs.dir, model.DB_FILENAME)
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document["assets"].append(dict(row, categories=[], tags=[]))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _saving_a_twin(self, name):
        """A converter whose last step is the real one, add_asset."""
        def convert(_model, _index, _target, render=True):
            saved = material_actions.add_asset(self.model,
                _karma_material(self, name), "", "", False)
            return bool(saved), types.SimpleNamespace(
                summary_lines=lambda: [])
        return convert

    def _assert_no_row_moved_inside(self, caught, verb):
        self.assertEqual(
            [], caught,
            "%s moved rows inside a layout-change pair - the shape that "
            "segfaults H21: %s" % (verb, caught))

    def test_convert_in_either_direction(self):
        for source, target, twin in (("Karma", "Redshift", "rs_twin"),
                                     ("Redshift", "Karma", "karma_twin")):
            with self.subTest(target=target):
                self.model.assets[1].renderer = source
                self._select(1)
                before = self.model.rowCount()
                with mock.patch.object(material_actions, "convert",
                                       self._saving_a_twin(twin)), \
                        test_support.row_moves_inside_a_layout_change(
                            self.model) as caught:
                    self.panel.convert_selected(target)
                self.assertEqual(before + 1, self.model.rowCount(),
                                 "premise: the conversion added no twin")
                self._assert_no_row_moved_inside(caught,
                                                 "Convert to %s" % target)

    def test_both_directions_report_in_the_words_they_always_did(self):
        """One verb, two directions: each summary names both renderers as the menus show them."""
        ui = mock.Mock()
        report = types.SimpleNamespace(summary_lines=lambda: ["a line"])
        for target, source, shown in (
                ("Redshift", "Karma", ("MaterialX", "Redshift")),
                ("Karma", "Redshift", ("Redshift", "MaterialX"))):
            with self.subTest(target=target):
                self.model.assets[1].renderer = source
                self._select(1)
                with mock.patch.object(material_actions, "convert",
                                       lambda _model, _index, _target, render=True: (True, report)), \
                        mock.patch.object(hou, "ui", ui, create=True):
                    self.panel.convert_selected(target)
                self.assertEqual(
                    ("Converted 1 of 1 %s material(s) to %s." % shown, "a line"),
                    (ui.displayMessage.call_args.args[0],
                     ui.displayMessage.call_args.kwargs.get("details")))

    def test_an_online_import(self):
        record = types.SimpleNamespace(kind="", category="", title="t")

        def importing(_record, _source, _resolution, library, *_a, **_k):
            saved = _k["save"](
                _karma_material(self, "online_twin"), "", "", False)
            return bool(saved), ""

        before = self.model.rowCount()
        with mock.patch.object(self.panel.online_import, "source_for",
                               lambda _record: (object(), "1k", "")), \
                mock.patch.object(matx_import, "import_record",
                                  importing), \
                test_support.row_moves_inside_a_layout_change(
                    self.model) as caught:
            ok, reason = self.panel.online_import.import_material(record)
        self.assertTrue(ok, reason)
        self.assertEqual(before + 1, self.model.rowCount())
        self._assert_no_row_moved_inside(caught, "an online import")

    def test_a_drop_on_a_sidebar_category(self):
        self._peer_adds_a_row(self.model, {"id": "PEER-DROP",
                                           "name": "Dropped elsewhere"})
        self._select(1)
        with test_support.row_moves_inside_a_layout_change(
                self.model) as caught:
            self.panel.assign_category_active("usds")
        self.assertIn("Dropped elsewhere",
                      [asset.name for asset in self.model.assets],
                      "premise: the save adopted nothing")
        self.assertEqual(["usds"], list(self.model.assets[1].categories))
        self._assert_no_row_moved_inside(caught, "a sidebar drop")

    def test_saving_over_an_existing_material(self):
        self._peer_adds_a_row(self.model, {"id": "PEER-OVER",
                                           "name": "Saved elsewhere"})

        def updating(_model, _row, _node):
            self.model.save()    # the update's own last step
            return "Karma"

        with mock.patch.object(material_actions, "update_asset_content",
                               updating), \
                test_support.row_moves_inside_a_layout_change(
                    self.model) as caught:
            self.panel._update_existing_asset(self.model.tile_key(1), None)
        self.assertIn("Saved elsewhere",
                      [asset.name for asset in self.model.assets],
                      "premise: the save adopted nothing")
        self._assert_no_row_moved_inside(caught, "Save Version")

    def test_editing_a_snippet(self):
        code = self.panel.code_model
        row = next(i for i, asset in enumerate(code.assets)
                   if str(asset.code or "").strip())
        self._peer_adds_a_row(code, {"id": "PEER-CODE",
                                     "name": "Typed elsewhere",
                                     "code": "@P.y += 1;",
                                     "renderer": "VEX"})

        def accepting(dialog):
            dialog._apply()    # Apply saves and the window stays; closing saves nothing more
            return 0

        with mock.patch.object(code_dialog.CodeDialog, "exec", accepting), \
                test_support.row_moves_inside_a_layout_change(
                    code, self.panel.code_category_model) as caught:
            self.panel.sections["code"]._edit_code_row(row)
        self.assertIn("Typed elsewhere",
                      [asset.name for asset in code.assets],
                      "premise: the save adopted nothing")
        self._assert_no_row_moved_inside(caught, "Edit Snippet")


class ARowHeldAcrossASaveIsFoundAgain(unittest.TestCase):
    """Every save takes in another machine's deletions, so a row number held across one names another."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _deleted_elsewhere(self, model, mat_id):
        """Another machine deletes `mat_id`; the next save of the file takes the deletion in."""
        self.assertTrue(model.save(), "premise: the baseline save failed")
        path = os.path.join(self.panel.prefs.dir, model.DB_FILENAME)
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document["assets"] = [row for row in document["assets"]
                              if str(row.get("id")) != str(mat_id)]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def test_a_drop_onto_a_new_category_moves_the_asset_dropped(self):
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        model = self.panel.material_model
        proxy = self.panel.material_sorted_model
        shown = [model.assets[proxy.mapToSource(proxy.index(row, 0)).row()]
                 for row in range(proxy.rowCount())]
        self.assertGreaterEqual(len(shown), 4, "premise: too few tiles")
        target = shown[2]
        self.panel.material_selection_model.select(
            proxy.index(2, 0),
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self._deleted_elsewhere(model, shown[0].mat_id)

        self.panel.assign_category_active("Brand New")

        self.assertEqual(
            ["Brand New"], list(target.categories),
            "the dropped asset kept its category: the list's save took in "
            "a deletion above it, and the row held from before named another")

    def test_an_edited_snippet_is_the_one_saved(self):
        code = self.panel.code_model
        rows = [row for row, asset in enumerate(code.assets)
                if row and str(asset.code or "").strip()]
        self.assertTrue(rows, "premise: no snippet below the first row")
        target = code.assets[rows[0]]
        self._deleted_elsewhere(code, code.assets[0].mat_id)

        def accepting(dialog):
            dialog._harvest()
            dialog.category = "Brand New"
            dialog.code = "// edited here"
            dialog.applied.emit()    # what Apply hands the section, with these two fields set
            return 0

        with mock.patch.object(code_dialog.CodeDialog, "exec", accepting):
            self.panel.sections["code"]._edit_code_row(rows[0])

        self.assertEqual(
            "// edited here", target.code,
            "the edit landed on another snippet: the category list's save "
            "took in a deletion above it, and the row held from before moved")

    def _material_tiles(self):
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        model = self.panel.material_model
        self.assertGreaterEqual(len(model.assets), 7, "premise: too few assets")
        return model

    @staticmethod
    def _ids(assets):
        return sorted(str(asset.mat_id) for asset in assets)

    def test_customize_moves_exactly_the_tiles_chosen(self):
        model = self._material_tiles()
        proxy = self.panel.material_sorted_model
        chosen = [model.assets[row] for row in (2, 4, 6)]
        target = "Moved Here"
        self.panel.category_model.check_add_category(target)
        self._deleted_elsewhere(model, model.assets[1].mat_id)
        indexes = [proxy.mapFromSource(model.index(model.assets.index(asset), 0))
                   for asset in chosen]
        self.panel.sections["material"].menu_customize(indexes, indexes[0])
        dialog = self.panel._icon_dialog
        combo = dialog.category_combo
        self.assertGreaterEqual(combo.findData(target), 0, "premise: not offered")
        combo.setCurrentIndex(combo.findData(target))
        dialog.accept_button.click()
        QtWidgets.QApplication.processEvents()

        moved = [asset for asset in model.assets if list(asset.categories) == [target]]
        self.assertEqual(self._ids(chosen), self._ids(moved),
                         "Customize moved other tiles: each move saves, and the first "
                         "save took in a deletion above the rows it held")

    def test_converting_a_selection_converts_exactly_the_tiles_chosen(self):
        model = self._material_tiles()
        proxy = self.panel.material_sorted_model
        shown = [model.assets[proxy.mapToSource(proxy.index(row, 0)).row()]
                 for row in range(proxy.rowCount())]
        for asset in shown:
            asset.renderer = "Karma"    # a stale row then converts another tile, never skips it
        chosen = [shown[row] for row in (2, 4, 6)]
        selection = self.panel.material_selection_model
        selection.clearSelection()
        for row in (2, 4, 6):
            selection.select(proxy.index(row, 0),
                             QtCore.QItemSelectionModel.SelectionFlag.Select
                             | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        self._deleted_elsewhere(model, shown[0].mat_id)
        converted = []

        def convert(_model, index, _target, render=True):
            converted.append(model.assets[index.row()])
            model.save()    # the twin's own save, which takes the deletion in
            return True, types.SimpleNamespace(summary_lines=lambda: [])

        with mock.patch.object(material_actions, "convert", convert):
            self.panel.convert_selected("Redshift")
        self.assertEqual(self._ids(chosen), self._ids(converted),
                         "Convert reached other tiles: each twin saves, and the first "
                         "save took in a deletion above the rows it held")

    def test_saving_over_several_materials_updates_exactly_those(self):
        model = self._material_tiles()
        chosen = [model.assets[row] for row in (2, 4, 6)]
        nodes = [types.SimpleNamespace(name=lambda i=i: "held%d" % i)
                 for i, _asset in enumerate(chosen)]    # the save names each in the status line
        where = {id(node): model.assets.index(asset)
                 for node, asset in zip(nodes, chosen)}
        self._deleted_elsewhere(model, model.assets[1].mat_id)
        updated = []

        def update(_model, row, _node):
            if 0 <= row < len(model.assets):
                updated.append(model.assets[row])
            model.save()    # the update's own last step, which takes the deletion in
            return "Karma"

        asking = types.SimpleNamespace(displayMessage=lambda *_a, **_k: 0)    # Save Version
        with mock.patch.object(hou, "selectedNodes", lambda: nodes), \
                mock.patch.object(hou, "ui", asking, create=True), \
                mock.patch.object(self.panel, "_find_existing_asset_row",
                                  lambda node: where[id(node)]), \
                mock.patch.object(library_policy, "allow_overwrite",
                                  lambda *_a: True), \
                mock.patch.object(material_actions, "update_asset_content", update):
            self.panel.save_asset()
        self.assertEqual(self._ids(chosen), self._ids(updated),
                         "Save Version wrote over other materials: each update saves, "
                         "and the first save took in a deletion above the rows it held")

    def test_deleting_a_selection_deletes_exactly_the_tiles_chosen(self):
        model = self._material_tiles()
        chosen = [model.assets[row] for row in (2, 4, 6)]
        elsewhere = model.assets[1]
        before = {str(asset.mat_id) for asset in model.assets}
        self._deleted_elsewhere(model, elsewhere.mat_id)
        self.panel.sections["material"].delete_rows(
            [model.index(model.assets.index(asset), 0) for asset in chosen])
        self.assertEqual(
            sorted(before - set(self._ids(chosen)) - {str(elsewhere.mat_id)}),
            self._ids(model.assets),
            "Delete removed other assets: each removal saves, and the first "
            "save took in a deletion above the rows it held")

    def test_one_edit_repaints_the_row_its_asset_moved_to(self):
        model = self._material_tiles()
        asset = model.assets[5]
        self._deleted_elsewhere(model, model.assets[1].mat_id)
        painted = []
        model.dataChanged.connect(
            lambda top, _bottom, _roles=(): painted.append(top.row()))
        model.set_tile_tags(5, "moved, below")
        self.assertIn(model.assets.index(asset), painted,
                      "the edit repainted the row its asset left, not the one it is on")


class CustomizeOffersTheOwningSectionsCategories(unittest.TestCase):
    """Customize lists the categories of the section whose tiles it edits; a mixed pick opens blank."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 0
        self.model = self.panel.cop_model
        for name in ("Rigs", "Terrain"):
            self.panel.cop_category_model.check_add_category(name)
        self.rows = [self._node_asset("rig_setup", "Rigs"),
                     self._node_asset("terrain_setup", "Terrain")]
        self.panel.section_tabs.setChecked("cop")
        QtWidgets.QApplication.processEvents()

    def _node_asset(self, name, category):
        """A real LOP network saved into the Node section under `category`."""
        lop = hou.node("/obj").createNode("lopnet", name)
        self.addCleanup(lop.destroy)
        lop.createNode("sphere")
        held = test_support.asset_ids(self.model)
        self.assertTrue(node_actions.add_asset(self.model, lop, category, "", False,
                                               name=name))
        saved, = test_support.arrived(self.model, held)
        return self.model.find_asset_row_by_id(saved.mat_id)

    def _customize(self, rows):
        proxy = self.panel.cop_sorted_model
        indexes = [proxy.mapFromSource(self.model.index(row, 0))
                   for row in rows]
        self.panel.sections["cop"].menu_customize(indexes, indexes[0])
        dialog = self.panel._icon_dialog
        self.assertIsNotNone(dialog, "Customize did not open")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_node_tile_is_offered_the_node_categories(self):
        combo = self._customize(self.rows[:1]).category_combo
        offered = [combo.itemData(i) for i in range(combo.count())
                   if combo.itemData(i)]
        self.assertEqual(self.panel.category_names_from(self.panel.cop_category_model), offered,
                         "a Node tile was offered another section's "
                         "categories")
        self.assertEqual("Rigs", base_dialog.chosen_category(combo))

    def test_an_icon_only_accept_moves_no_tile(self):
        dialog = self._customize(self.rows)
        opened_on = base_dialog.chosen_category(dialog.category_combo)
        dialog.face_combo.setCurrentIndex(tile_icons.FACES.index("custom"))
        dialog._choose("layers")
        dialog.accept_button.click()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(self.model.tile_icon(self.rows[0]),
                        "premise: the icon change did not land")
        self.assertEqual(
            [["Rigs"], ["Terrain"]],
            [list(self.model.assets[row].categories) for row in self.rows],
            "an icon-only Accept moved the tiles to another category")
        self.assertEqual("", opened_on,
                         "two tiles in two categories opened on a category")


class ADeleteOverASelectionSavesOnce(unittest.TestCase):
    """Five tiles deleted together cost one list write and one thumbnail-map rebuild."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.assertGreaterEqual(self.model.rowCount(), 6, "premise: six rows")
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.rows = [1, 2, 3, 4, 5]
        self.ids = [str(self.model.assets[row].mat_id) for row in self.rows]
        self.files = [path for mat_id in self.ids
                      for path in self.model.asset_files(mat_id).values()
                      if os.path.exists(path)]
        self.assertTrue(self.files, "premise: the assets own files")

    def _delete(self, refuse=False):
        from amaze.core import database, library
        save = database.DatabaseConnector.save
        with mock.patch.object(database.DatabaseConnector, "save",
                               autospec=True,
                               side_effect=(lambda db: False) if refuse
                               else save) as saves, \
                mock.patch.object(library.AssetLibrary, "rebuild_thumbs",
                                  autospec=True,
                                  side_effect=library.AssetLibrary.rebuild_thumbs
                                  ) as rebuilds:
            self.panel.active_section().delete_rows(
                [self.model.index(row, 0) for row in self.rows])
            QtWidgets.QApplication.processEvents()
        return saves.call_count, rebuilds.call_count

    def test_five_tiles_go_in_one_save_and_one_rebuild(self):
        saves, rebuilds = self._delete()
        self.assertEqual((1, 1), (saves, rebuilds),
                         "a five-tile delete saved %d times and rebuilt the "
                         "thumbnail maps %d times" % (saves, rebuilds))
        left = [str(a.mat_id) for a in self.model.assets]
        self.assertEqual([], [mat_id for mat_id in self.ids if mat_id in left])
        self.assertEqual([], [p for p in self.files if os.path.exists(p)],
                         "a deleted asset's files stayed behind")
        self.assertEqual(self.model.rowCount(), len(self.model._mat_paths))

    def test_a_refused_save_puts_every_row_back_and_keeps_every_file(self):
        before = [str(a.mat_id) for a in self.model.assets]
        self._delete(refuse=True)
        self.assertEqual(before, [str(a.mat_id) for a in self.model.assets],
                         "a refused delete did not put every row back where "
                         "it was")
        self.assertEqual(self.files, [p for p in self.files if os.path.exists(p)],
                         "a refused delete unlinked files")
        self.assertTrue(self.model.save(), "premise: the next save landed")
        path = os.path.join(self.panel.prefs.dir, "library.json")
        with open(path, encoding="utf-8-sig") as handle:
            on_disk = {str(row.get("id")) for row in json.load(handle)["assets"]}
        self.assertEqual(set(self.ids), set(self.ids) & on_disk,
                         "the declined delete reached disk with the next save")


class ACustomizeOverASelectionSavesOnce(unittest.TestCase):
    """Tags and a category typed into Customize over five tiles reach the list in ONE save."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.assertGreaterEqual(self.model.rowCount(), 6, "premise: six rows")
        self.rows = [1, 2, 3, 4, 5]
        self.ids = [str(self.model.assets[row].mat_id) for row in self.rows]

    def _apply(self, tags, category):
        from amaze.core import database
        self.panel.edit_tile_icon(
            self.model, None, [self.model.index(row, 0) for row in self.rows])
        dialog = self.panel._icon_dialog
        self.assertIsNotNone(dialog, "Customize did not open")
        self.addCleanup(dialog.deleteLater)
        dialog.canceled = False
        dialog.spec = {"name": "star", "bg": "#4af2a1", "ink": "dark"}
        dialog.new_tags = tags
        dialog.new_category = category
        with mock.patch.object(database.DatabaseConnector, "save",
                               autospec=True,
                               side_effect=database.DatabaseConnector.save) as save:
            dialog.finished.emit(1)
            QtWidgets.QApplication.processEvents()
        return save.call_count

    def _record(self, mat_id):
        row = self.model.find_asset_row_by_id(mat_id)
        return self.model.assets[row]

    def test_tags_and_a_category_over_five_tiles_save_once(self):
        saves = self._apply("probe-tag", "Probe Shelf")
        self.assertEqual(1, saves,
                         "Customize over five tiles wrote the list %d times"
                         % saves)
        for mat_id in self.ids:
            record = self._record(mat_id)
            self.assertIn("probe-tag", record.tags)
            self.assertEqual(["Probe Shelf"], list(record.categories))
        path = os.path.join(self.panel.prefs.dir, "library.json")
        with open(path, encoding="utf-8-sig") as handle:
            on_disk = {str(row.get("id")): row
                       for row in json.load(handle)["assets"]}
        for mat_id in self.ids:
            self.assertEqual(["Probe Shelf"], on_disk[mat_id]["categories"],
                             "the edit never reached the file")

    def test_an_edit_that_changes_nothing_saves_nothing(self):
        self._apply("probe-tag", "Probe Shelf")
        self.assertEqual(0, self._apply("probe-tag", "Probe Shelf"),
                         "re-applying what every tile already carries saved")


class _SavesThroughThePanel:
    """A fixture panel whose Save runs for real on fresh Karma builders, every dialog recorded."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.panel = test_support.fixture_panel(self)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)
        self.shown = []

    def _karma(self, count):
        assets = [asset for asset in self.panel.material_model.assets
                  if renderers.is_karma(asset.renderer)][:count]
        self.assertEqual(count, len(assets), "premise: too few Karma materials")
        return assets

    def _builders(self, count):
        return [render_nodes.build_karma_material(
            self.staging, "held%d" % number,
            lambda builder: builder.createNode("mtlxstandard_surface")).builder
            for number in range(count)]

    def _held(self, assets, builder=True):
        held = (self._builders(len(assets)) if builder else
                [self.staging.createNode("null", "held%d" % n) for n in range(len(assets))])
        for node, asset in zip(held, assets):
            node.setUserData("assetlib_id", str(asset.mat_id))
        return held

    def _list_of(self, model):
        return os.path.join(self.panel.prefs.dir, model.DB_FILENAME)

    def _answering(self, text, *_args, **kwargs):
        self.shown.append((text, kwargs["details"]) if kwargs.get("details") else text)    # a list rides in details
        return 0    # Save Version, the first button

    def _save(self, held, *patches):
        """The panel's Save over `held`, answered Save Version: (the dialogs after that question, log)."""
        with contextlib.ExitStack() as stack:
            for patch in (mock.patch.object(hou, "selectedNodes", lambda: held),
                          mock.patch.object(hou, "ui", types.SimpleNamespace(
                              displayMessage=self._answering), create=True),
                          mock.patch.object(library_policy, "allow_overwrite", lambda *_a: True),
                          *patches):
                stack.enter_context(patch)
            log = stack.enter_context(test_support.captured_log())
            self.panel.save_asset()
        return self.shown[1:], log


class ASaveVersionTheListCannotTakeIsSaidOnce(_SavesThroughThePanel, unittest.TestCase):
    """Save Version with the library list write refused: one status line after the batch, no dialog."""

    def _save_over(self, count):
        assets = self._karma(count)
        index = self._list_of(self.panel.material_model)
        shown, log = self._save(self._held(assets), test_support.full_disk_for(index))
        self.assertEqual([], shown, "a dialog joined the library's own alert")
        self.assertTrue(log.matching("could not save the library", "alert"),
                        "premise: the list write went through")
        return assets, log.messages("refuse")

    def test_one_update_names_the_material(self):
        assets, said = self._save_over(1)
        self.assertEqual([messages.MATERIAL_UPDATED_LIBRARY_NOT_SAVED % assets[0].name], said,
                         "the status line did not say the library was not saved")

    def test_several_updates_share_one_line(self):
        _assets, said = self._save_over(2)
        self.assertEqual([messages.MATERIALS_UPDATED_LIBRARY_NOT_SAVED % 2], said,
                         "the batch did not end on one line counting its unsaved updates")


class ASaveVersionSaysWhatItDidNotUpdateOnce(_SavesThroughThePanel, unittest.TestCase):
    """Every material Save Version did not update, named once with its reason, after the batch."""

    def _files(self, assets):
        model = self.panel.material_model
        found = []
        for asset in assets:
            with open(model.asset_files(asset.mat_id)["mat"], "rb") as handle:
                found.append(handle.read())
        return found

    def test_an_unset_ocio_is_said_once_and_nothing_is_written(self):
        assets = self._karma(2)
        before = self._files(assets)
        was = hou.getenv("OCIO") or ""
        hou.putenv("OCIO", "")    # an empty $OCIO counts as unset, as the save reads it
        self.addCleanup(hou.putenv, "OCIO", was)
        shown, _log = self._save(self._held(assets))
        self.assertEqual([messages.OCIO_NOT_SET], shown,
                         "an unset $OCIO was said more than once, or with Update failed after it")
        self.assertEqual(before, self._files(assets), "a material was written without $OCIO")

    def test_a_node_that_is_no_builder_is_one_sentence(self):
        assets = self._karma(1)
        shown, _log = self._save(self._held(assets, builder=False))
        self.assertEqual(
            [messages.MATERIAL_NOT_UPDATED % (assets[0].name, messages.UPDATE_REFUSED_NOT_A_BUILDER)],
            shown, "the refusal and Update failed came as two dialogs")

    def test_two_changed_on_disk_are_both_named_in_one_message(self):
        assets = self._karma(2)
        for asset in assets:
            path = self.panel.material_model.asset_files(asset.mat_id)["mat"]
            with open(path, "ab") as handle:
                handle.write(b"\0their-bytes")
            stat = os.stat(path)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        shown, log = self._save(self._held(assets))
        lines = "\n".join(messages.MATERIAL_NOT_UPDATED_LINE
                          % (asset.name, messages.UPDATE_REFUSED_CHANGED_ON_DISK) for asset in assets)
        self.assertEqual([(messages.MATERIALS_NOT_UPDATED, lines)], shown,
                         "the second material's refusal was not named, or came as its own dialog")
        self.assertEqual([], log.messages("alert"), "the refusal alerted beside the one message")

    def test_an_error_in_one_save_does_not_stop_the_batch(self):
        assets = self._karma(2)
        tried = []

        def failing(handler, node, *_args):
            tried.append(node.name())
            raise OSError(28, "No space left on device")

        try:
            shown, _log = self._save(self._held(assets), mock.patch.object(
                render_nodes.NodeHandler, "_save_copy", failing))
        except OSError as exc:
            self.fail("the error escaped Save Version, after %s: %s" % (tried, exc))
        self.assertEqual(["held0", "held1"], tried, "the error stopped the batch")
        lines = "\n".join(messages.MATERIAL_NOT_UPDATED_LINE
                          % (asset.name, OSError(28, "No space left on device")) for asset in assets)
        self.assertEqual([(messages.MATERIALS_NOT_UPDATED, lines)], shown,
                         "the errors were not named in the batch's one message")


class ASaveNewTheListCannotTakeIsSaidOnce(_SavesThroughThePanel, unittest.TestCase):
    """A new material or node setup whose list write fails: a status line, the library's alert alone."""

    def _dialog(self, name=""):
        return types.SimpleNamespace(categories="", tags="", fav=False, name=name)

    def _save_new(self, count):
        held = self._builders(count)
        index = self._list_of(self.panel.material_model)
        with test_support.full_disk_for(index), test_support.captured_log() as log, \
                mock.patch.object(hou, "ui", types.SimpleNamespace(
                    displayMessage=self._answering), create=True):
            self.panel.sections["material"].commit_save(held, held[0], self._dialog())
        self.assertEqual([], self.shown, "a dialog joined the library's own alert")
        self.assertEqual([], [text for text in log.messages("alert")
                              if "could not save the library" not in text],
                         "an alert beside the library's own said the material was not listed")
        return held, log.messages("refuse")

    def test_one_new_material_is_named(self):
        held, said = self._save_new(1)
        self.assertEqual([messages.ASSET_ADDED_LIBRARY_NOT_SAVED % held[0].name()], said,
                         "the status line did not say the library was not saved")

    def test_several_new_materials_share_one_line(self):
        _held, said = self._save_new(2)
        self.assertEqual([messages.MATERIALS_ADDED_LIBRARY_NOT_SAVED % 2], said,
                         "the save did not end on one line counting its unlisted materials")

    def test_a_new_node_setup_is_named(self):
        lop = hou.node("/obj").createNode("lopnet", "refused_setup")
        self.addCleanup(lop.destroy)
        lop.createNode("sphere")
        index = self._list_of(self.panel.cop_model)
        with test_support.full_disk_for(index), test_support.captured_log() as log, \
                mock.patch.object(hou, "selectedItems", lambda: [lop]), \
                mock.patch.object(hou, "ui", types.SimpleNamespace(
                    displayMessage=self._answering), create=True):
            self.panel.sections["cop"].commit_save([lop], lop, self._dialog("probe_setup"))
        self.assertEqual([], self.shown, "a dialog joined the library's own alert")
        self.assertEqual([messages.ASSET_ADDED_LIBRARY_NOT_SAVED % "probe_setup"],
                         log.messages("refuse"),
                         "the status line did not say the library was not saved")
        self.assertEqual([], [text for text in log.messages("alert")
                              if "could not save the library" not in text],
                         "an alert beside the library's own said the setup was not listed")


if __name__ == "__main__":
    unittest.main()
