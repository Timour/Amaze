"""The Grid area's OPERATIONS: one selection, one owner per verb. - BATCH 6 of the four-areas restructure, the second half of it. The area owns what is shown and in what order (test_grid_order.py) and it owns THE SELECTION AND WHAT IS DONE TO IT - which is where the copies were: - * Favourite was written FIVE times, once inside each section's right-click handler, each mapping the selection through its own proxy and calling a differently-named model method (`toggle_fav(index)` for the asset sections, `toggle_favorite(row)` for File and Color); * three of the five wrapped the call in `layoutAboutToBeChanged` / `layoutChanged` on the SOURCE model to force the grid to re-map, and two did not - so on File and Color, un-favouriting a tile with Favourites-only on left it in the grid with its star off. The invariant belongs to the proxy (core/grid_proxy.py) and now lives there, which is what lets every caller stop carrying it; * Update Preview was written three times and MISSING from a fourth. - A verb the Grid offers is now one method on the Section: the panel hands over the selection and never knows which model method a section calls or what a row is keyed by."""

import ast
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        self.panel._favourite_badge_clicked(self.proxy.index(1, 0))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            [not b for b in before], [self._fav(0), self._fav(1)],
            "one gesture on a selected tile's star did not star the "
            "whole selection")

    def test_a_click_OUTSIDE_the_selection_flips_only_the_clicked_tile(self):
        before = [self._fav(0), self._fav(2)]
        self._select(0)
        self.panel._favourite_badge_clicked(self.proxy.index(2, 0))
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


if __name__ == "__main__":
    unittest.main()
