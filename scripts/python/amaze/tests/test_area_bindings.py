"""THE NET for batches 4 to 9: what every context binds into each area, asserted by ACTIVATING a real context and reading the widgets back, and named by panel ATTRIBUTE rather than by class. ▸p/area-bindings"""

import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402


BINDINGS = {   # context key -> what it binds into each area, by ATTRIBUTE NAME, read off the six activation bodies as they stand today (panel.py `_activate_*` and `FolderSection.activate`): when a batch moves one of those, this table is what says the move kept its meaning, so a CHANGE here must be a deliberate line in that batch and never a repair to make the suite green again
    "material": {
        "grid": "material_sorted_model",
        "selection": "material_selection_model",
        "delegate": "thumb_delegate",
        "sidebar": "category_sorted_model",
    },
    "gradient": {
        "grid": "gradient_sorted_model",
        "selection": "gradient_selection_model",
        "delegate": "gradient_delegate",
        "sidebar": "gradient_category_sorted_model",  # CHANGED 2026-08-14, deliberately: Color's sidebar goes through the same CategoriesSidebarProxy as the asset sections (unsorted - the manual order round), where it was the bare model and the last odd-one-out pipeline
    },
    "cop": {
        "grid": "cop_sorted_model",
        "selection": "cop_selection_model",
        "delegate": "asset_delegate",  # SHARED with Code, deliberately - the roles are inherited from the material model, which is why this table names instances
        "sidebar": "cop_category_sorted_model",
    },
    "code": {
        "grid": "code_sorted_model",
        "selection": "code_selection_model",
        "delegate": "asset_delegate",
        "sidebar": "code_category_sorted_model",
    },
    "file": {
        "grid": "file_sorted_model",
        "selection": "file_selection_model",
        "delegate": "file_delegate",
        "sidebar": "file_folders_model",
    },
}

ONLINE_BINDINGS = {   # the Online world is a PARALLEL WORLD, not a section, but it drives the same four widgets, so it is pinned beside them - and CHANGED IN BATCH 5, on purpose and by this line: the delegate was `thumb_delegate`, borrowed from Materials, which gave the online grid a Version, Licence and Comments column no online record can ever fill, where it has its own now carrying only the roles matx_library actually has
    "grid": "matx_sorted_model",
    "selection": "matx_selection_model",
    "delegate": "matx_delegate",
    "sidebar": "matx_source_model",
}


class EveryLibraryBackedModelIsDeclaredBySection(unittest.TestCase):
    """WHICH MODELS A LIBRARY SWITCH REPOINTS is derived from the sections, the way `tile_delegates()` derives - so a ninth model joins by existing rather than by being remembered. - It was three hand-written lists in panel.py, each naming seven models where there are eight. `GradientCategories` - the Colors SIDEBAR - was in none of them, so after a library switch it kept library A's category names with library B's counts beside them. - The guard this replaces counted `switch_model_data()` calls in panel.py source, and could not see the eighth model at all: GradientCategories exposed `refresh()` instead, so the pattern did not match and the model was invisible to it. A source scan keyed on a SPELLING goes quiet rather than red for anything that does not use that spelling. - Both directions are asserted, because they fail differently: a declaration naming something the panel cannot repoint, and a repointable model no section declares (the eighth model's own shape - the one that catches the next one)."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @staticmethod
    def _declared():
        from amaze.panel import sections as sections_mod
        declared = set()
        for section_cls in sections_mod.SECTION_CLASSES:
            declared.update(getattr(section_cls, "library_model_attrs", ()))
        return declared

    def test_every_declared_attribute_exists_and_can_switch(self):
        declared = self._declared()
        self.assertTrue(declared, "no section declares a library model")
        broken = {}
        for attr in sorted(declared):
            model = getattr(self.panel, attr, None)
            if model is None:
                broken[attr] = "not built on the panel"
            elif not callable(getattr(model, "switch_model_data", None)):
                broken[attr] = "%s has no switch_model_data" % type(
                    model).__name__
        self.assertEqual(
            {}, broken,
            "a section declares a library-backed model the panel "
            "cannot repoint, so a library switch would leave it "
            "serving the old library: %s" % broken)

    def test_every_switchable_model_the_panel_builds_is_declared(self):
        declared = self._declared()
        undeclared = set()
        for attr in dir(self.panel):
            if attr.startswith("__") or attr in declared:
                continue
            try:
                value = getattr(self.panel, attr)
            except Exception:                            # noqa: BLE001
                continue
            if isinstance(value, type):
                continue
            if callable(getattr(value, "switch_model_data", None)):
                undeclared.add(attr)
        self.assertEqual(
            set(), undeclared,
            "these models can be repointed but no section declares "
            "them, so a library switch leaves them serving the "
            "previous library: %s" % sorted(undeclared))

    def test_the_panel_switches_through_the_one_derived_route(self):
        """And there is ONE walk, not three. Three copies is what let five siblings be added to the same lists while the eighth was added to none - so the copies are what the fix removes."""
        import inspect
        import re
        from amaze.panel import panel as panel_mod

        source = inspect.getsource(panel_mod)
        stray = re.findall(r"self\.\w*model\w*\.switch_model_data\(\)",
                           source)
        self.assertEqual(
            [], stray,
            "a hand-named model is switched outside "
            "switch_all_models(), which is how a list goes short: %s"
            % sorted(set(stray)))


class AreaBindingCase(unittest.TestCase):
    """One panel for the whole class - it is expensive, and every test here only reads what activation bound."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def activate(self, key):
        """Put the panel into one context and let Qt settle."""
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
            QtWidgets.QApplication.processEvents()
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            key, panel.current_section,
            "the panel did not switch to %s, so nothing below is about "
            "the section it claims" % key)
        return panel

    def bound(self, panel):
        return {
            "grid": panel.thumblist.model(),
            "selection": panel.thumblist.selectionModel(),
            "delegate": panel.thumblist.itemDelegate(),
            "sidebar": panel.cat_list.model() if panel.cat_list else None,
        }

    def _restore(self):
        """Put the shared panel back in a local world. - One panel serves the whole class, so a test that ENTERS the online world and leaves it there hands the next one a fixture it never asked for. On the base rather than on one class: two classes here go online now."""
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        section = panel._section()
        if section is not None:
            section.activate()
        QtWidgets.QApplication.processEvents()


BADGE_ROLES = {   # which badge each context's tiles carry and the role its own model must answer for it - THIS is the list that used to be invisible, a delegate built without a role painting nothing silently, so a section that forgot a badge was indistinguishable from a section that has no such badge; a model that CAN answer a badge's role beside a section that does not wire it is a defect the test below fails on, and the two deliberate exceptions are named with their reason because a bare exception list is how the first one got forgotten
    "open": "OpenSceneRole",
    "favourite": "FavoriteRole",
    "versions": "VersionsRole",
    "comment": "NotesRole",
}

EXPECTED_BADGES = {
    "material": {"favourite", "versions", "comment"},
    "cop": {"favourite", "comment"},  # NOT versions, although these three subclass MaterialLibrary and inherit VersionsRole: a version can only be minted by `MaterialLibrary.update_asset_content`, reached from one call site on `material_model` alone, so no Node, Code or Color asset can ever hold a second version - wiring it anyway gave both a Version column reading none on every row and a badge click that mapped through the MATERIAL proxy into an unrelated asset
    "code": {"favourite", "comment"},
    "file": {"favourite", "open", "comment"},  # File has the OPEN badge, which nothing else does: only a scene can be the one Houdini currently has open
    "gradient": {"favourite", "comment"},
}

ONLINE_BADGES = {"favourite"}   # the online world is READ-ONLY and is not a section: nothing there can be starred, commented or versioned and its model answers no such role, pinned so that giving it one is a deliberate line here


class EveryContextCarriesTheBadgesItsModelCanAnswer(AreaBindingCase):
    """A badge is a fact the section HAS, not a role someone remembered to pass (2026-08-05). - The art and the paint path became one family on 2026-08-01; the WIRING stayed four hand-written argument lists, and a missing entry failed silently. This is the half that makes the omission loud."""

    def test_each_section_carries_exactly_the_badges_it_should(self):
        for key, expected in EXPECTED_BADGES.items():
            with self.subTest(section=key):
                panel = self.activate(key)
                delegate = panel.thumblist.itemDelegate()
                self.assertEqual(
                    expected, set(delegate.badges()),
                    "%s's tiles do not carry the badges it should - a "
                    "badge wired nowhere paints nothing and says nothing"
                    % key)

    def test_a_model_that_can_answer_a_badge_has_it_wired(self):
        """The gate. A section whose model grows one of these roles and whose delegate is not updated fails HERE, rather than shipping a badge that never appears."""
        for key, expected in EXPECTED_BADGES.items():
            panel = self.activate(key)
            model = getattr(panel, BINDINGS[key]["grid"]).sourceModel()
            for badge, role_name in BADGE_ROLES.items():
                if not hasattr(model, role_name):
                    continue
                if badge in expected:
                    continue
                self.assertIn(
                    (key, badge),
                    (("cop", "versions"), ("code", "versions"),
                     ("gradient", "versions")),
                    "%s's model answers %s but its tiles carry no %s "
                    "badge, and that is not one of the exceptions "
                    "this file records a reason for" % (key, role_name,
                                                        badge))

    def test_the_online_world_carries_only_its_own(self):
        panel = self.panel
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(QtWidgets.QApplication.processEvents)
        self.addCleanup(panel.leave_online_world)
        self.assertEqual(
            ONLINE_BADGES, set(panel.thumblist.itemDelegate().badges()),
            "the online grid carries a badge no online record can fill")

    def test_the_table_and_the_expectations_name_the_same_badges(self):
        """Re-keyed with the table, not against a literal: a badge added to `delegates.BADGES` and to no section at all would otherwise pass every assertion above by being invisible to them."""
        from amaze.panel import delegates
        self.assertEqual(
            {badge.name for badge in delegates.BADGES}, set(BADGE_ROLES),
            "delegates.BADGES and this file disagree about which badges "
            "exist - a new one needs a role name and a line per section")


class TheGridIsBoundToItsOwnContext(AreaBindingCase):

    def test_every_section_binds_its_own_model_selection_and_delegate(self):
        for key, expected in BINDINGS.items():
            with self.subTest(section=key):
                panel = self.activate(key)
                actual = self.bound(panel)
                for area in ("grid", "selection", "delegate"):
                    self.assertIs(
                        actual[area], getattr(panel, expected[area]),
                        "%s bound the wrong %s - expected panel.%s. Two "
                        "sections share a delegate instance and two "
                        "share a proxy class, so a wrong binding here "
                        "looks right to an isinstance check and shows up "
                        "as the previous tab's tiles"
                        % (key, area, expected[area]))

    def test_no_two_sections_share_a_selection_model(self):
        """A shared selection model turns a click in one tab into the wrong asset in another - the failure the engine's key-not-row rule exists for, one level up."""
        seen = {}
        for key, expected in BINDINGS.items():
            seen.setdefault(expected["selection"], []).append(key)
        shared = {name: keys for name, keys in seen.items() if len(keys) > 1}
        self.assertEqual({}, shared,
                         "these sections share one selection model: %s"
                         % shared)


class TheSidebarIsBoundToItsOwnContext(AreaBindingCase):

    def test_every_section_binds_its_own_sidebar_model(self):
        for key, expected in BINDINGS.items():
            with self.subTest(section=key):
                panel = self.activate(key)
                self.assertIs(
                    self.bound(panel)["sidebar"],
                    getattr(panel, expected["sidebar"]),
                    "%s left the sidebar on another context's model, so "
                    "clicking a row filters the grid to nothing" % key)

    def test_the_sidebar_has_a_row_selected_after_every_activation(self):
        """cat_list has no persistent selection model, so setModel() always leaves it with nothing selected - every activation has to choose a row or the grid opens blank with nothing highlighted."""
        for key in BINDINGS:
            with self.subTest(section=key):
                panel = self.activate(key)
                model = panel.cat_list.model()
                if model is None or model.rowCount() == 0:
                    continue
                selection = panel.cat_list.selectionModel()
                self.assertTrue(
                    selection is not None and selection.hasSelection(),
                    "%s activated with nothing selected in the sidebar"
                    % key)


class TheToolbarFollowsTheContext(AreaBindingCase):

    CONVERTS = "file"   # the one section that OWNS the conversion bar - it is the only one that converts anything, so the only one allowed to leave it up

    def test_the_conversion_progress_bar_belongs_to_no_section(self):
        """It sits above the grid, and whichever section owned it last may have left it visible - so every activation hides it. - FILE IS EXCLUDED, and finding out why is the point. This asserted all five and was green for the module run and RED in the full suite on H22 only: File activates, queues its conversions, and `_on_texture_progress` legitimately puts the bar back up. Run alone the fixture images were already cached and nothing showed. An assertion that depends on whether work happened to be in flight is not an invariant - File gets its own test below."""
        for key in BINDINGS:
            if key == self.CONVERTS:
                continue
            with self.subTest(section=key):
                panel = self.activate(key)
                panel.texture_progress.setVisible(True)
                panel._section().activate()
                QtWidgets.QApplication.processEvents()
                self.assertTrue(   # isHidden(), NOT isVisible(): the fixture panel is never shown, so isVisible() is False for every widget in it whatever activation did and an assertFalse on it is green by construction, which is what the first version of this test was - isHidden() asks the only question that has an answer here, was this widget explicitly hidden
                    panel.texture_progress.isHidden(),
                    "%s activated and left another section's conversion "
                    "bar on screen" % key)

    def test_the_File_section_may_only_show_it_for_its_OWN_work(self):
        """The half the loop above cannot assert. File is allowed to leave the bar up - but only while it genuinely has conversions outstanding, never as a leftover from the section before it."""
        panel = self.activate(self.CONVERTS)
        QtWidgets.QApplication.processEvents()
        if panel.texture_progress.isHidden():
            return                      # nothing to convert; fine
        model = panel.file_files_model
        outstanding = getattr(model, "_progress_total", 0) or 0
        done = getattr(model, "_progress_done", 0) or 0
        self.assertGreater(
            outstanding, done,
            "the File section is showing the conversion bar with no "
            "conversions outstanding, which means it inherited it from "
            "the section before rather than raising it for its own work")

    def test_capture_is_offered_on_the_File_tab_and_nowhere_else(self):
        """NAMED, not looked up with a fallback. The first version of this asked for `btn_capture`, got None and SKIPPED - a pin that can skip is not a pin, and it would have skipped just as quietly on the day a batch renamed the real one."""
        button = self.panel.btn_hip_capture
        for key in BINDINGS:
            with self.subTest(section=key):
                panel = self.activate(key)
                self.assertEqual(
                    key == "file", not button.isHidden(),
                    "Capture is %s on the %s tab"
                    % ("hidden" if key == "file" else "showing", key))


class TheCommentsPaneFollowsTheContext(AreaBindingCase):
    """Comments is the fourth area, not an exception - and its subject is per-context: an asset id for the asset sections, a raw path for File rows, a uid for a gradient."""

    def test_every_section_answers_with_a_subject_or_with_nothing(self):
        for key in BINDINGS:
            with self.subTest(section=key):
                panel = self.activate(key)
                subject = panel._notes_subject()
                self.assertTrue(
                    subject is None or isinstance(subject, str),
                    "%s answered the Comments pane with %r, which is "
                    "neither a key nor 'no subject'" % (key, subject))
                if subject:
                    self.assertIn(
                        ":", subject,
                        "%s produced a comment key with no section "
                        "prefix (%r) - every store key is "
                        "'<section>:<id>'" % (key, subject))


class TheOnlineWorldBindsTheSameFourAreas(AreaBindingCase):
    """A PARALLEL world, not a view mode - but it drives the same four widgets, which is why it is pinned beside the sections. Batch 5 turns it into a context object with a delegate of its own; this table is what says that move kept its meaning."""

    def test_entering_binds_the_online_models(self):
        panel = self.activate("material")
        self.addCleanup(self._restore)
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        actual = self.bound(panel)
        for area, name in ONLINE_BINDINGS.items():
            self.assertIs(actual[area], getattr(panel, name),
                          "the online world bound the wrong %s - "
                          "expected panel.%s" % (area, name))

    def test_leaving_puts_back_the_section_you_came_from(self):
        panel = self.activate("gradient")
        self.addCleanup(self._restore)
        before = self.bound(panel)
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()
        after = self.bound(panel)
        for area in ("grid", "selection", "delegate", "sidebar"):
            self.assertIs(
                after[area], before[area],
                "coming back from the online world left the %s on "
                "something else" % area)

    def test_its_delegate_carries_no_role_the_online_model_lacks(self):
        """THE ONLINE DEAD-COLUMNS DEFECT, dissolved rather than fixed. - `_update_list_columns` decides a column EXISTS from the ACTIVE delegate's roles. Borrowing the Materials delegate therefore gave the online grid a Version column reading "none" on every row, plus Licence and Comments columns that nothing online can fill - the same defect shape as Node and Code borrowing it, one world over. The cure is not a branch that hides them: it is a delegate that never had the roles."""
        delegate = self.panel.matx_delegate
        model = self.panel.matx_online_model
        for role in ("_versions_role", "_licence_role", "_notes_role",
                     "_active_version_role", "_category_color_role"):
            self.assertFalse(
                getattr(delegate, role, None),
                "the online delegate carries %s, so the grid paints a "
                "column no online record can fill" % role)
        self.assertEqual(model.CategoryRole, delegate._category_role)  # ...and the roles it DOES carry are really the online model's, so this cannot pass by carrying nothing at all
        self.assertEqual(model.FavoriteRole, delegate._favorite_role)
        self.assertEqual(model.TagRole, delegate._tag_role)

    def test_entering_and_leaving_go_through_ONE_path(self):
        """Entering used to call its own activation directly and skip everything `_on_tab_toggled` does afterwards - so the Capture button kept the state the section you left had given it, and the Comments pane went on pointing at the local asset."""
        panel = self.activate("file")
        self.addCleanup(self._restore)
        self.assertFalse(panel.btn_hip_capture.isHidden(),
                         "Capture should be offered on the File tab, so "
                         "this test is not set up to prove anything")

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            panel.btn_hip_capture.isHidden(),
            "Capture is still live in the online world, where there is "
            "no scene tile to capture onto")
        self.assertFalse(   # NOT `assertIsNone(panel._notes_subject())`: the fixture blocks the network, so the online grid has no rows, nothing is selected, and the lookup returns None before it ever reaches the question - that assertion was green with the whole mechanism removed, and these two are what it was trying to say
            panel.online_context.takes_comments,
            "the online world claims a comment can be written against "
            "an online record, which has no library asset to carry it")
        subject_source = inspect.getsource(type(panel)._notes_subject)
        self.assertIn(
            "takes_comments", subject_source,
            "the Comments subject lookup decides by testing which WORLD "
            "it is in again, instead of asking the context")
        self.assertNotIn(
            "_is_online()", subject_source,
            "the Comments subject lookup still branches on _is_online()")


class TheOnlineWorldIsASKEDLikeAnySection(AreaBindingCase):
    """Six panel paths tested which WORLD they were in, and the online context already answered every one of them (part-four audit A12). - `_section()` hands back the OnlineContext while the online world shows, and that context already declared `search_hint`, `filter_text`, `filter_favorites` and the base's empty `SIDEBAR_MENU` - so four of the six branches guarded behaviour the context was carrying anyway, and deleting them changes nothing. The other two held a body nothing else could reach; those move onto the context, beside the verbs they belong with. - NAMED, NEVER COUNTED (test_grid_menu's law): a count says there is one too many without saying which. ELEVEN `_is_online()` reads survive deliberately and none of them is a section question - which tab strip to build, which world a progress bar is drawing over, whether the Online chip is lit, which world the debug log is recording. Those ask about the WORLD, which is the one thing a context cannot answer for itself."""

    DISSOLVED = (   # the six, and what answers each one instead
        ("catlist_rc_menu",
         "OnlineContext inherits the base's empty SIDEBAR_MENU, and "
         "open_catlist_menu returns on no entries"),
        ("_sync_filter_placeholder",
         "OnlineContext.search_hint is already the empty hint"),
        ("filter_thumb_view",
         "OnlineContext.filter_text already asks the SOURCE"),
        ("filter_favs",
         "OnlineContext.filter_favorites is already the documented no-op"),
        ("update_selected_cat",
         "OnlineContext.select_category carries the catalogue filter"),
        ("import_asset_auto",
         "OnlineContext.double_click carries the import-to-scene"),
    )

    def test_the_context_declares_every_verb_the_branches_relied_on(self):
        """What each deleted branch now lands on - deleting a branch is only safe while the context still answers it, so this is the other half of the pin, and without it retiring a verb from OnlineContext would leave the panel silently doing nothing at all."""
        from amaze.panel import sections
        online = sections.OnlineContext
        self.assertEqual(
            "", online.search_hint,
            "the online world wants a placeholder now, so deleting "
            "_sync_filter_placeholder's branch changed what is drawn")
        self.assertEqual(
            (), getattr(online, "SIDEBAR_MENU", None),
            "the online world declares a sidebar menu now, so "
            "catlist_rc_menu's deleted branch is no longer a no-op")
        for verb in ("filter_text", "filter_favorites",
                     "select_category", "double_click"):
            self.assertIn(
                verb, vars(online),
                "OnlineContext does not declare %s, so the panel branch "
                "deleted for it has nothing to land on and the online "
                "world silently does nothing" % verb)

    def test_the_six_no_longer_ask_which_world_they_are_in(self):
        offenders = [name for name, _why in self.DISSOLVED
                     if "_is_online" in inspect.getsource(
                         getattr(type(self.panel), name))]
        self.assertEqual(
            [], offenders,
            "%s still branches on _is_online(), and the online context "
            "already answers it" % ", ".join(offenders))

    def test_the_sidebar_still_filters_the_catalogue_when_online(self):
        """The moved body, RUN rather than read. - A source scan cannot see that `select_category` was moved onto a context the sidebar never reaches - and the fixture blocks the network, so this drives the category models directly rather than asserting on rows that will never arrive."""
        from amaze.core import matx_sources

        panel = self.activate("material")
        self.addCleanup(self._restore)
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()

        online = panel.matx_online_model  # SEEDED, never waited for: the fixture blocks the network so the catalogue is empty and there is no category to click, and a skipTest on that would be exactly the dead cover this module opens on - `_all` is the model's own cache, test_generator seeds it the same way, and the source is read back off the model rather than named because entering the world sets a source filter and a record outside it is filtered away before `categories()` ever sees it
        previous = online._all
        online._all = [matx_sources.MatxRecord(
            source=online._source_filter, uid="a12-probe",
            title="A12 Probe", category="Metal")]
        self.addCleanup(setattr, online, "_all", previous)
        source_model = panel.matx_source_model
        source_model.refresh()

        row = next((r for r in range(source_model.rowCount())
                    if source_model.category_at(r) == "Metal"), None)
        self.assertIsNotNone(
            row, "the seeded category never reached the online sidebar, "
                 "so clicking it cannot prove anything")
        panel.online_context.select_category(source_model.index(row, 0))
        self.assertEqual(   # `_filters` is the proxy's own store: MultiFilterProxyModel offers setFilter/removeFilter and no reader, so this is the only way to see WHICH value landed rather than just that the row count moved
            "Metal",
            panel.matx_sorted_model._filters.get(online.CategoryRole),
            "selecting an online category did not narrow the catalogue, "
            "so the branch moved off the panel without arriving")


class EveryTileDelegateIsSweptByEverySweep(AreaBindingCase):
    """The Node/Code list-column defect, made unwritable. - `asset_delegate` was added deliberately - so Node and Code would stop painting a Version column reading "none" on every row - and joining it to the sweeps was left to whoever remembered. Nobody did. It was in NONE of the three hand-written lists that reach every tile delegate: the accent sweep at construction, the accent sweep in show_prefs, and `set_list_columns`. So Node and Code rows were laid out with column widths the panel had never told that delegate about, which showed up as the type column starting under the category column and running halfway into comments. - One accessor now, built FROM the sections, so a section that arrives with a delegate of its own joins by existing."""

    def test_every_sections_delegate_is_in_the_one_list(self):
        panel = self.panel
        swept = panel.tile_delegates()
        for key, expected in BINDINGS.items():
            with self.subTest(section=key):
                self.assertIn(
                    getattr(panel, expected[key and "delegate"]), swept,
                    "%s's delegate is not in the list every sweep walks, "
                    "so it never hears about column widths or the accent"
                    % key)

    def test_the_fourth_delegate_is_really_in_it(self):
        """Named, because it is the one that was missing - a loop over the table above would go green on the day the table itself is written short."""
        self.assertIn(self.panel.asset_delegate, self.panel.tile_delegates(),
                      "asset_delegate - Node's and Code's - is out of the "
                      "sweep again")
        self.assertEqual(
            len(set(id(d) for d in self.panel.tile_delegates())),
            len(self.panel.tile_delegates()),
            "the same delegate is in the list twice, so a sweep does its "
            "work on it twice")

    def test_no_delegate_lays_out_a_LIST_ROW_any_more(self):
        """This used to assert the opposite: that every tile delegate had been TOLD the ten list-column widths, because each one laid its own row out from them. - List mode is a real QTableView since 2026-08-04. The delegates paint GRID tiles; the table paints its own cells and asks its header where the columns are. A delegate still being told column widths would mean the retired fit had come back."""
        panel = self.activate("material")
        self.assertTrue(panel.tile_delegates(),
                        "no tile delegates found - this checks nothing")
        self.assertFalse(
            hasattr(panel, "_apply_list_columns"),
            "the hand-rolled column fit is back")


    def _back_to(self, mode):
        self.panel.prefs.view_mode = mode
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    def test_no_site_writes_the_list_out_by_hand(self):
        """The defect was three hand-written tuples, not one wrong one - so the pin is that there are none."""
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "panel.py"),
                      encoding="utf-8").read()
        offenders = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.For):
                continue
            names = {n.attr for n in ast.walk(node.iter)
                     if isinstance(n, ast.Attribute)}
            if len([n for n in names if n.endswith("_delegate")]) > 1:
                offenders.append(node.lineno)
        self.assertEqual(
            [], offenders,
            "a sweep is spelling the tile delegates out by hand again, "
            "at panel.py line(s) %s - that list has been one short three "
            "times" % offenders)


class TheBindingsAreDeclaredNotHandWritten(unittest.TestCase):
    """The direction of travel, and it has arrived. - Every section activates through its own `activate()`, binding by named attributes and differing from a sibling only by which models it names. No activation body is left in the panel - this used to record how far the move had got, and now it is the BAN that keeps one from coming back. - The online world is the one thing that never became a Section: it is deliberately absent from `enabled_sections`, so its entry point lives on the panel as `enter_online()`, named for what it does."""

    def test_no_activation_body_lives_in_the_panel(self):
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "panel.py"),
                      encoding="utf-8").read()
        bodies = sorted(
            node.name for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef)
            and node.name.startswith("_activate_"))
        self.assertEqual(
            [], bodies,
            "an activation body is back in the panel. Activation belongs "
            "to the section that owns it (FolderSection.activate is the "
            "pattern); the online world's entry is enter_online(), which "
            "routes through _apply_context like every section: %s"
            % bodies)

    _CHAINS_THE_SCAN_CANNOT_FOLLOW = ("menu_load", "menu_copy_to")   # menu verbs whose import chain leaves panel.py, so the scan below cannot follow it - NAMED, because a scan that silently covered less than it looks like is worse than one that says where it stops, and everything the scan CAN follow is found without appearing here

    _SCENE_API = ("createNode(", "createOutputNode(", "loadItemsFromFile(",   # Houdini's own scene-mutating calls: the seed is the HOST's API rather than our verb names, so adding an import verb of our own is followed automatically and only a new Houdini API would need a line here
                  "moveNodesTo(", "copyNodesTo(", "setDisplayFlag(",
                  "setCurrent(", "setSelected(")

    def test_every_scene_importing_menu_verb_preserves_the_view(self):
        """A menu verb that reaches into the scene must put back what it disturbed - either by routing through the click door (which wraps) or by carrying the wrapper itself. - The File section's geometry import carried neither, so Import on a .bgeo row moved the artist's current node and display flag with no way back, while Load, Copy To and Import to Scene beside it all preserved. The guard could not see it: it named THREE verbs by hand and there are five, with its own docstring claiming it was pinned so a fourth could not ship bare. - Derived now, from a reachability scan over panel.py seeded on Houdini's own scene API - so a new verb of ours is followed rather than remembered."""
        import ast
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        panel_source = open(os.path.join(root, "panel", "panel.py"),
                            encoding="utf-8").read()
        section_source = open(os.path.join(root, "panel", "sections.py"),
                              encoding="utf-8").read()

        bodies = {node.name: (ast.get_source_segment(panel_source, node) or "")
                  for node in ast.walk(ast.parse(panel_source))
                  if isinstance(node, ast.FunctionDef)}
        reaching = {name for name, body in bodies.items()
                    if any(call in body for call in self._SCENE_API)}
        growing = True
        while growing:                       # transitive, to a fixed point
            growing = False
            for name, body in bodies.items():
                if name in reaching:
                    continue
                if set(re.findall(r"self\.(\w+)\(", body)) & reaching:
                    reaching.add(name)
                    growing = True
        self.assertTrue(
            reaching, "the scan found no scene-reaching panel method at "
                      "all - it is keyed on names that no longer exist")

        bare = []   # PER CALL, never per function: checking the menu verb's whole body for the wrapper is the same disease as a test satisfied by a comment, since `menu_import` calls the door for images AND `import_geo_asset` for geometry, so one `click_on_row` anywhere in it would vouch for a bare sibling call three lines below - each scene-reaching call answers for itself
        for node in ast.walk(ast.parse(section_source)):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name.startswith("menu_")):
                continue
            body = ast.get_source_segment(section_source, node) or ""
            menu_wraps = "preserving_selection_and_current" in body
            called = set(re.findall(r"panel\.(\w+)\(", body))
            for verb in sorted(called & reaching):
                if menu_wraps or "preserving_selection_and_current" in \
                        bodies.get(verb, ""):
                    continue
                bare.append("%s -> %s" % (node.name, verb))
            if (node.name in self._CHAINS_THE_SCAN_CANNOT_FOLLOW
                    and not menu_wraps):
                bare.append("%s (chain outside panel.py)" % node.name)
        self.assertEqual(
            [], bare,
            "these menu verbs reach into the scene without preserving "
            "what they disturb, so the artist's current node and "
            "display flag move with no way back: %s" % bare)

    def test_no_section_dispatches_back_into_the_panel_to_activate(self):
        """BATCH 4 moved four of the five. What is left is the ONLINE world's, and batch 5 is where that goes - so this asserts the `activate_method` indirection is gone from the sections, not merely unused."""
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "sections.py"),
                      encoding="utf-8").read()
        assigned = [
            node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "activate_method"
                    for t in node.targets)
            and getattr(node.value, "value", None)]
        self.assertEqual(
            [], assigned,
            "a section still activates by naming a panel method, at "
            "sections.py line(s) %s - which is the indirection batch 4 "
            "removed" % assigned)


class TheReleaseVerbsLiveOnTheirSections(unittest.TestCase):
    """ROADMAP line 24, slice B2: the release bodies are the section's own. `sections.drop_verb` resolves section-first with the panel as a TEMPORARY fallback; a verb that drifts back onto the panel would resolve there silently once the section copy went missing, so both halves are pinned - the verb is defined by its section class, and panel.py defines no method of that name any more."""

    _MOVED = (   # (section class name, verb) - the six that line 24's B1/B2 moved, `_edit_code_row` having been on B1's list and travelled with B2
        ("MaterialSection", "drop_material_at_release"),
        ("CopSection", "drop_cop_at_release"),
        ("CodeSection", "drop_code_at_release"),
        ("CodeSection", "_edit_code_row"),
        ("FileSection", "drop_geo_at_release"),
        ("GradientSection", "apply_gradient_to_node"),
    )

    def test_each_moved_verb_is_defined_by_its_own_section(self):
        from amaze.panel import sections
        missing = [
            "%s.%s" % (cls_name, verb)
            for cls_name, verb in self._MOVED
            if verb not in vars(getattr(sections, cls_name))]
        self.assertEqual(
            [], missing,
            "these release verbs are not defined by the section that "
            "declares them, so they resolve through the temporary "
            "panel fallback line 24's B3 deletes: %s" % missing)

    def test_the_panel_no_longer_defines_them(self):
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "panel.py"),
                      encoding="utf-8").read()
        moved = {verb for _cls, verb in self._MOVED}
        strays = sorted(
            node.name for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name in moved)
        self.assertEqual(
            [], strays,
            "panel.py grew back a copy of a moved release verb - the "
            "section's copy would shadow it through drop_verb while "
            "every direct panel call reached the stale one: %s" % strays)

    def test_every_rule_named_verb_is_defined_by_its_section(self):
        """DERIVED, not a hand list: walk every DROP / DROP_BY_KIND declaration and the carrier-type verb, and require the named verb to be callable on the declaring section class. This is what makes the resolver's panel fallback removable - a rule whose verb resolves nowhere must fail HERE, at declaration altitude, not as a miss in a release handler."""
        from amaze.panel import sections
        missing = []
        for cls in sections.SECTION_CLASSES:
            rules = []
            if getattr(cls, "DROP", None) is not None:
                rules.append(cls.DROP)
            rules.extend(getattr(cls, "DROP_BY_KIND", {}).values())
            names = {name for rule in rules for name in (
                rule.on_node, rule.on_space, rule.resolve, rule.outside,
                rule.click_on_node, rule.click_resolve) if name}
            if getattr(cls, "carrier_type_verb", ""):
                names.add(cls.carrier_type_verb)
            for name in sorted(names):
                if not callable(getattr(cls, name, None)):
                    missing.append("%s.%s" % (cls.__name__, name))
        self.assertEqual(
            [], missing,
            "these declared verbs do not resolve on their own section, "
            "and there is no panel fallback any more: %s" % missing)

    def test_the_resolver_has_no_panel_fallback(self):
        """Line 24 B3 removed it; the signature is the pin. A resolver that can reach the panel is a resolver a verb can silently drift back through."""
        from amaze.panel import sections
        params = list(
            inspect.signature(sections.drop_verb).parameters)
        self.assertEqual(
            ["section", "name"], params,
            "drop_verb takes %s - a parameter beyond (section, name) "
            "is a fallback surface" % params)


if __name__ == "__main__":
    unittest.main()
