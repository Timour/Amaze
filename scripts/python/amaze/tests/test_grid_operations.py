"""The Grid area's OPERATIONS: one selection, one owner per verb. - BATCH 6 of the four-areas restructure, the second half of it. The area owns what is shown and in what order (test_grid_order.py) and it owns THE SELECTION AND WHAT IS DONE TO IT - which is where the copies were: - * Favourite was written FIVE times, once inside each section's right-click handler, each mapping the selection through its own proxy and calling a differently-named model method (`toggle_fav(index)` for the asset sections, `toggle_favorite(row)` for File and Color); * three of the five wrapped the call in `layoutAboutToBeChanged` / `layoutChanged` on the SOURCE model to force the grid to re-map, and two did not - so on File and Color, un-favouriting a tile with Favourites-only on left it in the grid with its star off. The invariant belongs to the proxy (core/grid_proxy.py) and now lives there, which is what lets every caller stop carrying it; * Update Preview was written three times and MISSING from a fourth. - A verb the Grid offers is now one method on the Section: the panel hands over the selection and never knows which model method a section calls or what a row is keyed by."""

import ast
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

from amaze.core import library_policy, matx_import, tile_icons  # noqa: E402
from amaze.dialogs import base_dialog, code_dialog  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE =os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TILE_CONTEXTS = ("AssetSection", "FileSection", "GradientSection")  # the contexts that show tiles a person can act on


def menu_verbs_calling(*attributes):
    """Every `menu_*` verb in sections.py that calls one of these methods, as "name:line". - These scans used to walk the six `_rc_menu` handlers in panel.py. Those are gone (batch 6), so the same scan over the same file would now find nothing and pass whatever the code did - the vacuous shape practice.md names. A copy of one of these verbs would be written as a `menu_*` method beside the table, so that is what is read."""
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

    def test_each_one_can_toggle_a_favourite(self):
        for name in TILE_CONTEXTS:
            with self.subTest(context=name):
                self.assertTrue(
                    callable(getattr(getattr(sections, name),
                                     "toggle_favourite", None)),
                    "%s cannot favourite its own selection, so the "
                    "panel has to know how for it" % name)

    def test_a_context_with_no_tiles_answers_harmlessly(self):
        """The online world has rows but no favourite state - the star is disabled there, and the verb must be a no-op rather than an error if anything ever reaches it."""
        context = sections.OnlineContext.__new__(sections.OnlineContext)
        self.assertFalse(sections.OnlineContext.takes_favourites)
        context.toggle_favourite([])          # must not raise


class OnlyASectionThatRENDERSOffersUpdatePreview(unittest.TestCase):
    """Update Preview was written three times, and the fourth section with a `render_thumbnail` method was offered it for exactly one commit before a live test showed the entry doing nothing at all - which was the correct outcome, and the more interesting fact. - A preview is either RENDERED or DERIVED. Materials and Node assets render: a real renderer runs over saved files and can produce a different picture than last time. Code and Color are derived - a snippet is painted from its own text under a CONTENT-ADDRESSED key (`_preview_key` = code hash + language), a palette from its ramp - so an edit repaints them by itself and a re-render repaints the identical image. - Having the method is not the test. Being able to produce a DIFFERENT picture is."""

    def test_the_sections_that_RENDER_offer_it(self):
        for name in ("MaterialSection", "CopSection", "FileSection"):
            with self.subTest(context=name):
                context = getattr(sections, name)
                self.assertTrue(
                    context.offers_preview_update,
                    "%s runs a real render and cannot ask for one" % name)
                self.assertTrue(callable(
                    getattr(context, "update_preview", None)))

    def test_the_sections_that_DERIVE_do_not(self):
        for name in ("GradientSection", "CodeSection"):
            with self.subTest(context=name):
                self.assertFalse(
                    getattr(sections, name).offers_preview_update,
                    "%s offers to re-render a preview that is painted "
                    "from the row's own content - it would repaint the "
                    "same image and look broken" % name)

    def test_CODE_still_has_the_METHOD_it_inherits(self):
        """It is not removed, only not offered: it inherits AssetSection, and the flag is what the menu reads. - CALLABLE, not hasattr - `update_preview = None` satisfies hasattr and would break the day anything calls it (the sabotage round found exactly that)."""
        self.assertTrue(callable(
            getattr(sections.CodeSection, "update_preview", None)))

    def _preview_gate(self, name):
        """Update Preview is ONE row of the shared tail, in every section's table, so a label check says nothing and what decides is the row's `shown` GATE - whether that answer survives into a real menu is driven end to end in test_grid_menu.py."""
        entry = next(e for e in sections.GRID_MENU_TAIL
                     if e.label == "Update Preview")
        self.assertTrue(
            entry.shown,
            "Update Preview is unconditional in the shared tail, so "
            "every section offers it whatever it can do")
        context = getattr(sections, name)(None)  # a panel-less instance: the gate reads facts about the SECTION, and the one override that reads models answers False for an absent one rather than raising
        return getattr(context, entry.shown)([], None)

    def test_no_derived_section_puts_it_in_a_MENU(self):
        for name in ("CodeSection", "GradientSection"):
            with self.subTest(context=name):
                self.assertFalse(
                    self._preview_gate(name),
                    "%s offers to re-render a derived preview, which "
                    "does nothing a person can see" % name)

    def test_the_sections_that_render_DO_put_it_in_theirs(self):
        """The other half - a flag nothing reads is not a rule."""
        for name in ("MaterialSection", "CopSection"):
            with self.subTest(context=name):
                self.assertTrue(self._preview_gate(name))

    def test_FILE_asks_about_the_SELECTION_not_only_the_section(self):
        """The one section where the two questions differ: it CAN re-render (`offers_preview_update` is True), and a selection of scene captures or OS icons still cannot - so the gate is a method there and a flag everywhere else."""
        self.assertTrue(sections.FileSection.offers_preview_update)
        self.assertFalse(
            self._preview_gate("FileSection"),
            "File offered Update Preview for an empty selection, which "
            "holds no image or geometry row to re-render")


class DeleteIsONEShapeWithFourSetsOfWORDS(unittest.TestCase):
    """Delete was written four times, and every copy had the same shape: count the DISTINCT source rows, ask with a sentence that says what goes and how many, remove HIGHEST ROW FIRST because a removal shifts everything below it, then refresh the sidebar because a category may just have emptied. - Only the sentence is really per-section - a material's files, a node asset's networks, a snippet's applied code, a palette's applied ramps. The descending order is the part a fifth copy would get wrong, silently: ascending removal deletes the wrong rows and only for multi-selections."""

    DELETING = ("MaterialSection", "CopSection", "CodeSection",   # the contexts whose Delete removes a LIBRARY record - File is deliberately absent, its rows being files on disk and the section having no Delete at all
                "GradientSection")

    def test_the_FILE_section_offers_no_delete_at_all(self):
        """A File row is somebody's photograph or scene on disk. The section browses locations; it does not own what is in them."""
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

    def test_COLOR_quotes_the_palette_by_NAME(self):
        """the UI text register is the source for every user-facing string, and it gives Color the only prompt that names the thing: a palette is picked by its label, and the label is the whole identity a person has for it."""
        prompt = sections.GradientSection.delete_prompt(1, "Sunset")
        self.assertIn('"Sunset"', prompt)
        self.assertIn("gradient goes for good", prompt)

    def test_the_others_ignore_the_name(self):
        """One signature, so the panel never asks which section wants it - and four sections that do not put a name in the sentence."""
        for name in ("MaterialSection", "CopSection", "CodeSection"):
            with self.subTest(context=name):
                context = getattr(sections, name)
                self.assertEqual(context.delete_prompt(1),
                                 context.delete_prompt(1, "Sunset"))

    def test_the_prompts_are_not_all_the_same_sentence(self):
        """The wording is the one part that is genuinely per-section: what goes for good, and what is NOT affected."""
        prompts = {getattr(sections, name).delete_prompt(1)
                   for name in self.DELETING}
        self.assertEqual(
            len(self.DELETING), len(prompts),
            "the sections share a delete sentence, so at least two are "
            "telling the user about the wrong thing")

    def test_no_menu_deletes_rows_itself(self):
        offenders = menu_verbs_calling(
            "remove_asset", "remove_user_gradient")
        self.assertEqual(
            [], offenders,
            "a right-click verb still removes rows itself, at %s - "
            "which is where the highest-row-first rule has to be "
            "remembered" % offenders)


class DeletingSEVERALRowsRemovesTHOSERows(unittest.TestCase):
    """The rule a fifth copy would get wrong. Removing row 1 shifts row 2 into its place, so ascending removal deletes a neighbour - and only ever on a multi-selection, which is why it survives hand-testing."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.assertGreater(self.model.rowCount(), 3,
                           "need four materials to delete two")

    def test_the_rows_that_go_are_the_rows_that_were_CHOSEN(self):
        going = [str(self.model.assets[1].mat_id),
                 str(self.model.assets[2].mat_id)]
        staying = [str(a.mat_id) for i, a in enumerate(self.model.assets)
                   if i not in (1, 2)]
        indexes = [self.model.index(1, 0), self.model.index(2, 0)]

        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.panel._section().delete_rows(indexes)
        QtWidgets.QApplication.processEvents()

        left = [str(a.mat_id) for a in self.model.assets]
        self.assertEqual(
            staying, left,
            "the wrong rows went - removing low-to-high shifts every "
            "row below the one just removed")
        for gone in going:
            self.assertNotIn(gone, left)


class TheCUSTOMIZEDialogSurvivesAModelRESET(unittest.TestCase):
    """The audit's find, and a REGRESSION this session introduced. - `QPersistentModelIndex` tracks rows across inserts and removals - but `endResetModel()` invalidates EVERY one of them even when nothing was removed. `FileFiles._load()` is a full reset, and the File section reaches it on any ordinary refresh: closing Preferences does it twice, and so does Show All Files on the sidebar menu. - So the dialog that used to paint the WRONG tile started painting NOTHING - the icon and, on a single selection, the new tile name both dropped silently. IDENTITY, not a Qt index and not a row number: every model family already keys its icons by something stable (an asset id, a file path, a palette uid) and now says so through `tile_key(row)`."""

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

    def test_a_RESET_that_moves_nothing_still_applies_the_icon(self):
        model = self.panel.material_model
        self.assertGreater(model.rowCount(), 1, "need two assets")
        target = str(model.assets[1].mat_id)
        dialog = self._open_on(model, 1)

        # a bare reset - every row is exactly where it was, and every persistent index is dead anyway
        model.beginResetModel()
        model.endResetModel()
        QtWidgets.QApplication.processEvents()

        self._ok(dialog)

        by_id = {str(a.mat_id): row for row, a in enumerate(model.assets)}
        self.assertIn(target, by_id, "the asset vanished")
        self.assertTrue(
            model.tile_icon(by_id[target]),
            "the icon was dropped: a model reset killed the held "
            "indexes and the dialog had nothing left to apply to")

    def test_a_reset_that_REORDERS_still_finds_the_right_asset(self):
        """The case row numbers get wrong and identity does not."""
        model = self.panel.material_model
        self.assertGreater(model.rowCount(), 2, "need three assets")
        target = str(model.assets[2].mat_id)
        bystander = str(model.assets[0].mat_id)
        dialog = self._open_on(model, 2)

        model.beginResetModel()
        model.assets.reverse()
        model.endResetModel()
        QtWidgets.QApplication.processEvents()

        self._ok(dialog)

        by_id = {str(a.mat_id): row for row, a in enumerate(model.assets)}
        self.assertTrue(model.tile_icon(by_id[target]),
                        "the chosen asset did not get the icon")
        self.assertFalse(
            model.tile_icon(by_id[bystander]),
            "the icon landed on a different asset - the rows were "
            "re-ordered under the open dialog")

    def test_every_tile_model_says_what_its_rows_are_KEYED_by(self):
        """The three families, one question. Without it the panel has to know that a material is an id, a file is a path and a palette is a uid."""
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
    """The five copies, as a source fact - a sixth section would have been a sixth copy, and the two that forgot the repaint show how that ends."""

    def test_no_right_click_handler_calls_a_model_toggle(self):
        offenders = menu_verbs_calling("toggle_fav", "toggle_favorite")
        self.assertEqual(
            [], offenders,
            "a right-click verb still favourites a row itself, at "
            "%s - which is the copy the two that forgot to repaint came "
            "from" % offenders)

    def test_no_right_click_handler_emits_a_LAYOUT_change(self):
        """No menu verb opens the pair BY HAND. - Two different reasons, one rule. Around a favourite toggle the pair was a caller forcing the grid to re-map because the proxy did not re-test a changed row - the proxy does now, so it is unnecessary and expensive. Around a category rename it is legitimate (the contents change wholesale), but written by hand it has no `finally`: if the second of two renames raises, every attached view is left mid-layout-change for the rest of the session. - `ui_helpers.relayout()` is the one way to say it, and it is what makes the second case safe - so this test forbids the raw signal rather than the intent. (The 26 hand-written sites are a batch 10 item; the sidebar verbs are three of them and were taken 2026-08-04 because this test found them.)"""
        with open(os.path.join(PACKAGE, "panel", "sections.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        verbs = [node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)
                 and node.name.startswith("menu_")]
        self.assertTrue(verbs, "no menu verbs found to check")
        offenders = []
        for verb in verbs:
            for call in ast.walk(verb):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "emit"
                        and isinstance(call.func.value, ast.Attribute)
                        and call.func.value.attr.startswith("layout")):
                    offenders.append("%s:%d" % (verb.name, call.lineno))
        self.assertEqual(
            [], offenders,
            "a right-click verb opens a layout change by hand, at %s "
            "- use ui_helpers.relayout(), which closes it in a finally"
            % offenders)

    def test_the_PANEL_never_opens_a_layout_change_by_hand(self):
        """The same rule, across the whole panel (2026-08-04). - Twenty-one hand-written opens lived here, in thirteen groups, none of them in a `finally`. They are `relayout()` now. This forbids the OPENING signal specifically, because that is the half that makes a promise: `layoutAboutToBeChanged` tells every attached view a change is coming and that `layoutChanged` will say when it is over, and a raise in between means that is never said. - The bare closing half has its own rule and its own reason, in the next test - they fail for different causes and say so."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        offenders = []
        for call in ast.walk(tree):
            if (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and isinstance(call.func.value, ast.Attribute)
                    and call.func.value.attr == "layoutAboutToBeChanged"):
                offenders.append(call.lineno)
        self.assertEqual(
            [], offenders,
            "panel.py opens a layout change by hand at line(s) %s - use "
            "ui_helpers.relayout(), which closes it in a finally"
            % offenders)

    def test_the_PANEL_never_emits_a_bare_layoutChanged(self):
        """The CLOSING half alone, which is a native crash (2026-08-05). - Seven of these lived here as a "re-map now" nudge with no opening half, and the previous test said so and let them stand. They are gone, because the nudge is not free: a bare `layoutChanged.emit()` SEGFAULTS H21 (research.md, measured 2026-08-04 against a control that mutates without emitting, so it is the signal and not the change). Qt describes the two as a pair - announce, restore persistent indexes, release - and a view told only that it is over was never given the chance to remember what it had to restore. - Third of the same family: remove-wrapped, insert-wrapped and bare-closing all crash H21 and all pass on H22, each reasoned safe before it was measured. - Six of the seven were compensating for nothing - the mutators under them (`check_add_category`, `normalize_categories`, `removeRow`) all emit the real structural contract already, and the proxy re-sorts and re-filters off that. The seventh was the real one: it announced a row-count change on the folder model after writing straight to prefs, and it routes through `FolderListModel.remove_folder` now. - The rule is panel.py's, not the tree's: a MODEL emits this legitimately from inside its own structural bookkeeping (see `ui_helpers.relayout`, which closes the pair in a `finally`)."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        offenders = []
        for call in ast.walk(tree):
            if (isinstance(call, ast.Call)
                    and not call.args
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and isinstance(call.func.value, ast.Attribute)
                    and call.func.value.attr == "layoutChanged"):
                offenders.append(call.lineno)
        self.assertEqual(
            [], offenders,
            "panel.py emits a bare layoutChanged at line(s) %s - it "
            "segfaults H21. Let the model's own begin/end contract "
            "announce the change, or wrap the change in "
            "ui_helpers.relayout()" % offenders)


class FavouritingWorksInEverySection(unittest.TestCase):
    """Through the real panel and the real models: the verb has to actually flip the star in all three archetypes, or one of them has been quietly wired to nothing."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _first_row(self, key, displaced=False):
        """`displaced` filters the grid down to the LAST row, so the row under test sits at proxy 0 and somewhere else in the source. A verb that acts on the proxy's row number then acts on the wrong asset - and without it the two numbers agree and no assertion can tell (the sabotage round said exactly that)."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        self.assertIsNotNone(proxy, "the %s tab has no grid" % key)
        self.assertGreater(proxy.rowCount(), 0,
                           "the %s fixture is empty, so this test "
                           "cannot say anything" % key)
        context = panel._section()
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
        self.panel._section().filter_text("")
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
        """The entry point every menu calls. It used to BE the material implementation - `toggle_fav()` reached for `material_model` by name - so a panel-level verb that quietly keeps doing that works perfectly in Materials and does nothing anywhere else. Checked in a section that is NOT Materials, for that reason."""
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
        """The live defect, in the sections that had it: the star goes out and the tile stays, with the filter saying favourites."""
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
        context = self.panel._section()
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
    """Customize opens NON-MODALLY - it has to, because its Custom Color button opens Houdini's own picker and a native modal lands UNDER a Qt exec loop (research.md). So the library can move while the dialog is open: a save appends, a delete shifts every row after it, a reload rebuilds the lot. - The handler captured plain ROW NUMBERS at open. Delete a tile while the dialog is up, press OK, and the icon lands on whatever now sits at that row - a different asset, silently."""

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
        """Through the PANEL's door, not the dialog's constructor: the constructor is already covered, and an empty field on a tagged tile is the failure being defended against."""
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
        """Delete the very tile being customised and the choice has no subject left. Applying it to the row number would paint the asset that moved into its place."""
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
    """The tile's star button flips every SELECTED row when the clicked tile is one of them, and just its own tile when it is not (settled 2026-08-21) - and only delegates whose grid can serve the flip wire the click at all."""

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

    def test_a_click_INSIDE_the_selection_flips_every_selected_row(self):
        before = [self._fav(0), self._fav(1)]
        self._select(0, 1)
        self.panel.thumb_delegate._badge_clicks["favourite"](self.proxy.index(1, 0))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            [not b for b in before], [self._fav(0), self._fav(1)],
            "one gesture on a selected tile's star did not star the "
            "whole selection")

    def test_a_click_OUTSIDE_the_selection_flips_only_the_clicked_tile(self):
        before = [self._fav(0), self._fav(2)]
        self._select(0)
        self.panel.thumb_delegate._badge_clicks["favourite"](self.proxy.index(2, 0))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            [before[0], not before[1]], [self._fav(0), self._fav(2)],
            "a click outside the selection reached beyond its own tile")

    def test_which_delegates_offer_the_star_button(self):
        """Every LOCAL grid wires the star click; the online grid wires none, because an online record has no favourite state to flip."""
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

    def test_every_delegate_that_DRAWS_the_comment_badge_wires_it(self):
        """Derived from the delegates the sections actually built, so a section arriving with a delegate of its own joins by existing rather than by somebody remembering a fifth registration line."""
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
        def convert(_index, _target):
            saved = self.model.add_asset(
                _karma_material(self, name), "", "", False)
            return bool(saved), types.SimpleNamespace(
                summary_lines=lambda: [])
        return convert

    def _assert_no_row_moved_inside(self, caught, verb):
        self.assertEqual(
            [], caught,
            "%s moved rows inside a layout-change pair - the shape that "
            "segfaults H21: %s" % (verb, caught))

    def test_convert_to_redshift(self):
        self.model.assets[1].renderer = "Karma"
        self._select(1)
        before = self.model.rowCount()
        with mock.patch.object(self.model, "convert",
                               self._saving_a_twin("rs_twin")), \
                test_support.row_moves_inside_a_layout_change(
                    self.model) as caught:
            self.panel.convert_selected("Redshift")
        self.assertEqual(before + 1, self.model.rowCount(),
                         "premise: the conversion added no twin")
        self._assert_no_row_moved_inside(caught, "Convert to Redshift")

    def test_convert_to_karma(self):
        self.model.assets[1].renderer = "Redshift"
        self._select(1)
        before = self.model.rowCount()
        with mock.patch.object(self.model, "convert",
                               self._saving_a_twin("karma_twin")), \
                test_support.row_moves_inside_a_layout_change(
                    self.model) as caught:
            self.panel.convert_selected("Karma")
        self.assertEqual(before + 1, self.model.rowCount(),
                         "premise: the conversion added no twin")
        self._assert_no_row_moved_inside(caught, "Convert to Karma")

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
                with mock.patch.object(self.model, "convert",
                                       lambda _index, _target: (True, report)), \
                        mock.patch.object(hou, "ui", ui, create=True):
                    self.panel.convert_selected(target)
                self.assertEqual(
                    "Converted 1 of 1 %s material(s) to %s.\n\na line"
                    % shown, ui.displayMessage.call_args.args[0])

    def test_an_online_import(self):
        record = types.SimpleNamespace(kind="", category="", title="t")

        def importing(_record, _source, _resolution, library, *_a, **_k):
            saved = library.add_asset(
                _karma_material(self, "online_twin"), "", "", False)
            return bool(saved), ""

        before = self.model.rowCount()
        with mock.patch.object(self.panel, "_online_source_for",
                               lambda _record: (object(), "1k", "")), \
                mock.patch.object(matx_import, "import_record",
                                  importing), \
                test_support.row_moves_inside_a_layout_change(
                    self.model) as caught:
            ok, reason = self.panel.import_online_material(record)
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

        def updating(_row, _node):
            self.model.save()    # the update's own last step
            return "Karma"

        with mock.patch.object(self.model, "update_asset_content",
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
            dialog._on_accept()
            return 1

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
            dialog._on_accept()
            dialog.category = "Brand New"
            dialog.code = "// edited here"
            return 1

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

        def convert(index, _target):
            converted.append(model.assets[index.row()])
            model.save()    # the twin's own save, which takes the deletion in
            return True, types.SimpleNamespace(summary_lines=lambda: [])

        with mock.patch.object(model, "convert", convert):
            self.panel.convert_selected("Redshift")
        self.assertEqual(self._ids(chosen), self._ids(converted),
                         "Convert reached other tiles: each twin saves, and the first "
                         "save took in a deletion above the rows it held")

    def test_saving_over_several_materials_updates_exactly_those(self):
        model = self._material_tiles()
        chosen = [model.assets[row] for row in (2, 4, 6)]
        nodes = [object() for _asset in chosen]
        where = {id(node): model.assets.index(asset)
                 for node, asset in zip(nodes, chosen)}
        self._deleted_elsewhere(model, model.assets[1].mat_id)
        updated = []

        def update(row, _node):
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
                mock.patch.object(model, "update_asset_content", update):
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
        self.assertTrue(self.model.add_asset(lop, category, "", False,
                                             name=name))
        return len(self.model.assets) - 1

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
        self.assertEqual(self.panel.get_cop_category_names(), offered,
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
            self.panel._section().delete_rows(
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


if __name__ == "__main__":
    unittest.main()
