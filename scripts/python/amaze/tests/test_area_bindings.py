"""THE NET for batches 4 to 9: what every context binds into each area.

BATCH 3 of the four-areas restructure. Tests only - no behaviour
changes here, deliberately, and it lands before any code moves.

The four areas are already ONE WIDGET EACH. There is one Grid, one
Sidebar, one Toolbar row and one Comments pane, and every section - the
Online world included - points those same widgets at different models
and delegates. What is NOT shared is the code that configures them:
`MatLibPanel` owns all four areas at once, so "point the grid at a
context" is written six separate times. Batches 4 to 9 move that
knowledge onto the Section and then split the panel into area modules.

**These pins RUN the panel rather than reading it.** That is the whole
reason the batch exists, in the roadmap's own words: moving code
between modules loses its imports and only running finds out. A source
scan would go green on a module that no longer imports what it calls.
So each test activates a real context and reads the widgets back.

The expected values are ATTRIBUTE NAMES on the panel, not classes. Two
sections share the `asset_delegate` instance and two more share a proxy
CLASS, so an isinstance check cannot tell a correctly-bound grid from
one left on a sibling's model - which is the exact failure a batch that
moves activation code produces.
"""

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


#: context key -> what it binds into each area, by ATTRIBUTE NAME.
#:
#: Read off the six activation bodies as they stand today
#: (panel.py `_activate_*` and `FolderSection.activate`). When a batch
#: moves one of those, this table is what says the move kept its
#: meaning - so a CHANGE here must be a deliberate line in that batch,
#: never a repair to make the suite green again.
BINDINGS = {
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
        "sidebar": "gradient_categories_model",
    },
    "cop": {
        "grid": "cop_sorted_model",
        "selection": "cop_selection_model",
        # SHARED with Code, deliberately - the roles are inherited from
        # the material model. Which is why this table names instances.
        "delegate": "asset_delegate",
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

#: The Online world is a PARALLEL WORLD, not a section - but it drives
#: the same four widgets, so it is pinned beside them.
#:
#: CHANGED IN BATCH 5, on purpose and by this line: the delegate was
#: `thumb_delegate`, borrowed from Materials, which gave the online
#: grid a Version, Licence and Comments column that no online record
#: can ever fill. It has its own now, carrying only the roles
#: matx_library actually has.
ONLINE_BINDINGS = {
    "grid": "matx_sorted_model",
    "selection": "matx_selection_model",
    "delegate": "matx_delegate",
    "sidebar": "matx_source_model",
}


class AreaBindingCase(unittest.TestCase):
    """One panel for the whole class - it is expensive, and every test
    here only reads what activation bound."""

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


#: Which badge each context's tiles carry, and the role its own model
#: must answer for it. THIS is the list that used to be invisible: a
#: delegate built without a role painted nothing, silently - no badge,
#: no error, no way to notice - so "this section forgot a badge" was
#: indistinguishable from "this section has no such badge".
#:
#: A model that CAN answer a badge's role and a section that does not
#: wire it is a defect, and the test below fails on it. The two
#: deliberate exceptions are named, with the reason, because a bare
#: exception list is how the first one got forgotten.
BADGE_ROLES = {
    "open": "OpenSceneRole",
    "favourite": "FavoriteRole",
    "versions": "VersionsRole",
    "comment": "NotesRole",
}

EXPECTED_BADGES = {
    "material": {"favourite", "versions", "comment"},
    # NOT versions, although CopLibrary subclasses MaterialLibrary and
    # inherits VersionsRole. A version can only be minted by
    # `MaterialLibrary.update_asset_content`, which is reached from one
    # call site on `material_model` alone - so no Node or Code asset can
    # ever hold a second version. Wiring it anyway gave both a "Version"
    # column reading "none" on every row, and a badge click that mapped
    # through the MATERIAL proxy into an unrelated asset.
    "cop": {"favourite", "comment"},
    "code": {"favourite", "comment"},
    # File has the OPEN badge, which nothing else does: only a scene can
    # be the one Houdini currently has open.
    "file": {"favourite", "open", "comment"},
    "gradient": {"favourite", "comment"},
}

#: The online world is READ-ONLY and is not a section: nothing there can
#: be starred, commented or versioned, and its model answers no such
#: role. Pinned so that giving it one is a deliberate line here.
ONLINE_BADGES = {"favourite"}


class EveryContextCarriesTheBadgesItsModelCanAnswer(AreaBindingCase):
    """A badge is a fact the section HAS, not a role someone remembered
    to pass (2026-08-05).

    The art and the paint path became one family on 2026-08-01; the
    WIRING stayed four hand-written argument lists, and a missing entry
    failed silently. This is the half that makes the omission loud.
    """

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
        """The gate. A section whose model grows one of these roles and
        whose delegate is not updated fails HERE, rather than shipping a
        badge that never appears."""
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
                    (("cop", "versions"), ("code", "versions")),
                    "%s's model answers %s but its tiles carry no %s "
                    "badge, and that is not one of the two exceptions "
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
        """Re-keyed with the table, not against a literal: a badge added
        to `delegates.BADGES` and to no section at all would otherwise
        pass every assertion above by being invisible to them."""
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
        """A shared selection model turns a click in one tab into the
        wrong asset in another - the failure the engine's key-not-row
        rule exists for, one level up."""
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
        """cat_list has no persistent selection model, so setModel()
        always leaves it with nothing selected - every activation has to
        choose a row or the grid opens blank with nothing highlighted."""
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

    #: The one section that OWNS the conversion bar - it is the only
    #: one that converts anything, so it is the only one allowed to
    #: leave it up.
    CONVERTS = "file"

    def test_the_conversion_progress_bar_belongs_to_no_section(self):
        """It sits above the grid, and whichever section owned it last
        may have left it visible - so every activation hides it.

        FILE IS EXCLUDED, and finding out why is the point. This
        asserted all five and was green for the module run and RED in
        the full suite on H22 only: File activates, queues its
        conversions, and `_on_texture_progress` legitimately puts the
        bar back up. Run alone the fixture images were already cached
        and nothing showed. An assertion that depends on whether work
        happened to be in flight is not an invariant - File gets its
        own test below."""
        for key in BINDINGS:
            if key == self.CONVERTS:
                continue
            with self.subTest(section=key):
                panel = self.activate(key)
                panel.texture_progress.setVisible(True)
                panel._section().activate()
                QtWidgets.QApplication.processEvents()
                # isHidden(), NOT isVisible(). The fixture panel is
                # never shown, so isVisible() is False for every widget
                # in it whatever activation did - an assertFalse on it
                # is green by construction, which is what the first
                # version of this test was. isHidden() asks the only
                # question that has an answer here: was this widget
                # explicitly hidden?
                self.assertTrue(
                    panel.texture_progress.isHidden(),
                    "%s activated and left another section's conversion "
                    "bar on screen" % key)

    def test_the_File_section_may_only_show_it_for_its_OWN_work(self):
        """The half the loop above cannot assert. File is allowed to
        leave the bar up - but only while it genuinely has conversions
        outstanding, never as a leftover from the section before it."""
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
        """NAMED, not looked up with a fallback. The first version of
        this asked for `btn_capture`, got None and SKIPPED - a pin that
        can skip is not a pin, and it would have skipped just as
        quietly on the day a batch renamed the real one."""
        button = self.panel.btn_hip_capture
        for key in BINDINGS:
            with self.subTest(section=key):
                panel = self.activate(key)
                self.assertEqual(
                    key == "file", not button.isHidden(),
                    "Capture is %s on the %s tab"
                    % ("hidden" if key == "file" else "showing", key))


class TheCommentsPaneFollowsTheContext(AreaBindingCase):
    """Comments is the fourth area, not an exception - and its subject
    is per-context: an asset id for the asset sections, a raw path for
    File rows, a uid for a gradient."""

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
    """A PARALLEL world, not a view mode - but it drives the same four
    widgets, which is why it is pinned beside the sections. Batch 5
    turns it into a context object with a delegate of its own; this
    table is what says that move kept its meaning."""

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
        """THE ONLINE DEAD-COLUMNS DEFECT, dissolved rather than fixed.

        `_update_list_columns` decides a column EXISTS from the ACTIVE
        delegate's roles. Borrowing the Materials delegate therefore
        gave the online grid a Version column reading "none" on every
        row, plus Licence and Comments columns that nothing online can
        fill - the same defect shape as Node and Code borrowing it, one
        world over. The cure is not a branch that hides them: it is a
        delegate that never had the roles."""
        delegate = self.panel.matx_delegate
        model = self.panel.matx_online_model
        for role in ("_versions_role", "_licence_role", "_notes_role",
                     "_active_version_role", "_category_color_role"):
            self.assertFalse(
                getattr(delegate, role, None),
                "the online delegate carries %s, so the grid paints a "
                "column no online record can fill" % role)
        # ...and the roles it DOES carry are really the online model's,
        # so this cannot pass by carrying nothing at all.
        self.assertEqual(model.CategoryRole, delegate._category_role)
        self.assertEqual(model.FavoriteRole, delegate._favorite_role)
        self.assertEqual(model.TagRole, delegate._tag_role)

    def test_entering_and_leaving_go_through_ONE_path(self):
        """Entering used to call its own activation directly and skip
        everything `_on_tab_toggled` does afterwards - so the Capture
        button kept the state the section you left had given it, and
        the Comments pane went on pointing at the local asset."""
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
        # NOT `assertIsNone(panel._notes_subject())` - the fixture
        # blocks the network, so the online grid has no rows, nothing is
        # selected, and the lookup returns None before it ever reaches
        # the question. That assertion was green with the whole
        # mechanism removed. These two are what it was trying to say.
        self.assertFalse(
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

    def _restore(self):
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        section = panel._section()
        if section is not None:
            section.activate()
        QtWidgets.QApplication.processEvents()


class EveryTileDelegateIsSweptByEverySweep(AreaBindingCase):
    """The Node/Code list-column defect, made unwritable.

    `asset_delegate` was added deliberately - so Node and Code would
    stop painting a Version column reading "none" on every row - and
    joining it to the sweeps was left to whoever remembered. Nobody
    did. It was in NONE of the three hand-written lists that reach
    every tile delegate: the accent sweep at construction, the accent
    sweep in show_prefs, and `set_list_columns`. So Node and Code rows
    were laid out with column widths the panel had never told that
    delegate about, which was reported as "the type column started under
    the category column and ran halfway into comments".

    One accessor now, built FROM the sections, so a section that
    arrives with a delegate of its own joins by existing."""

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
        """Named, because it is the one that was missing - a loop over
        the table above would go green on the day the table itself is
        written short."""
        self.assertIn(self.panel.asset_delegate, self.panel.tile_delegates(),
                      "asset_delegate - Node's and Code's - is out of the "
                      "sweep again")
        self.assertEqual(
            len(set(id(d) for d in self.panel.tile_delegates())),
            len(self.panel.tile_delegates()),
            "the same delegate is in the list twice, so a sweep does its "
            "work on it twice")

    def test_no_delegate_lays_out_a_LIST_ROW_any_more(self):
        """This used to assert the opposite: that every tile delegate
        had been TOLD the ten list-column widths, because each one laid
        its own row out from them.

        List mode is a real QTableView since 2026-08-04. The delegates
        paint GRID tiles; the table paints its own cells and asks its
        header where the columns are. A delegate still being told
        column widths would mean the retired fit had come back.
        """
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
        """The defect was three hand-written tuples, not one wrong
        one - so the pin is that there are none."""
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
    """The direction of travel, asserted so batches 4-9 can be measured
    against it rather than argued about.

    `FolderSection.activate()` already binds through named attributes
    and differs from a sibling only by which models it names. The other
    four still call back into `_activate_*` bodies inside the panel.
    This test does not demand the move - it RECORDS how far it has got,
    and its number is what a later batch changes deliberately."""

    def test_how_many_activation_bodies_still_live_in_the_panel(self):
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "panel.py"),
                      encoding="utf-8").read()
        bodies = sorted(
            node.name for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef)
            and node.name.startswith("_activate_"))
        self.assertEqual(
            ["_activate_online_materials"], bodies,
            "the set of activation bodies inside the panel changed. That "
            "is the point of batches 4 and 5 - update this list IN the "
            "batch that moves one, so the move is a deliberate line and "
            "not a green suite nobody looked at: %s" % bodies)

    def test_every_scene_importing_menu_verb_preserves_the_view(self):
        """The drag and click dispatchers wrap the artist's selection,
        current node and therefore the view; the menu dispatcher does
        not, so each scene-importing verb must carry the wrapper
        itself - the File section's import verb already does. The
        three that reach the scene are pinned here so a fourth cannot
        ship bare."""
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source = open(os.path.join(root, "panel", "sections.py"),
                      encoding="utf-8").read()
        tree = ast.parse(source)
        bare = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    "menu_load", "menu_copy_to", "menu_import_to_scene"):
                body = ast.get_source_segment(source, node) or ""
                if "preserving_selection_and_current" not in body:
                    bare.append("%s:%d" % (node.name, node.lineno))
        self.assertEqual(
            [], bare,
            "these menu verbs import into the scene without the "
            "preserve wrapper, so a menu import can jump the view: %s"
            % bare)

    def test_no_section_dispatches_back_into_the_panel_to_activate(self):
        """BATCH 4 moved four of the five. What is left is the ONLINE
        world's, and batch 5 is where that goes - so this asserts the
        `activate_method` indirection is gone from the sections, not
        merely unused."""
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


if __name__ == "__main__":
    unittest.main()
