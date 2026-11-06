"""Each context's bindings per area, read back by attribute after activation. ▸p/area-bindings"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402


BINDINGS = {   # context key -> what it binds into each area, by attribute name; a change must be deliberate
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
        "sidebar": "gradient_category_sorted_model",  # Color's sidebar goes through the same CategoriesSidebarProxy as the asset sections
    },
    "cop": {
        "grid": "cop_sorted_model",
        "selection": "cop_selection_model",
        "delegate": "asset_delegate",
        "sidebar": "cop_category_sorted_model",
    },
    "code": {
        "grid": "code_sorted_model",
        "selection": "code_selection_model",
        "delegate": "code_delegate",  # its own delegate: its tile adds Run and Edit
        "sidebar": "code_category_sorted_model",
    },
    "file": {
        "grid": "file_sorted_model",
        "selection": "file_selection_model",
        "delegate": "file_delegate",
        "sidebar": "file_folders_model",
    },
}

ONLINE_BINDINGS = {   # a parallel world driving the same four widgets, with a delegate carrying only its own roles
    "grid": "matx_sorted_model",
    "selection": "matx_selection_model",
    "delegate": "matx_delegate",
    "sidebar": "matx_source_model",
}


class EveryLibraryBackedModelIsDeclaredBySection(unittest.TestCase):
    """Models a library switch repoints are derived from the sections; asserted in both directions."""

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


class AreaBindingCase(unittest.TestCase):
    """One panel for the whole class; every test here only reads what activation bound."""

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
        """Put the shared panel back in a local world, so no test inherits the online one."""
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        section = panel._section()
        if section is not None:
            section.activate()
        QtWidgets.QApplication.processEvents()


BADGE_ROLES = {   # badge per context and the role its model must answer; exceptions carry their reason
    "open": "OpenSceneRole",
    "favourite": "FavoriteRole",
    "versions": "VersionsRole",
    "comment": "NotesRole",
    "execute": "RendererRole",    # the language: drawn for one value, so the role alone says nothing
    "edit": "",                   # no role: on every tile that lists it
    "renderer": "RendererRole",   # drawn for the renderers Amaze offers, each with its own art
}

EXPECTED_BADGES = {
    "material": {"favourite", "versions", "comment", "renderer"},
    "cop": {"favourite", "comment"},  # NOT versions: VersionsRole is inherited, and no Node asset keeps any
    "code": {"favourite", "execute", "versions", "edit", "comment"},
    "file": {"favourite", "open", "comment"},  # only File has the open badge: only a scene can be the one Houdini has open
    "gradient": {"favourite", "comment"},
}

ONLINE_BADGES = {"favourite"}   # the online world is read-only: nothing there can be starred, commented or versioned


class EveryContextCarriesTheBadgesItsModelCanAnswer(AreaBindingCase):
    """A badge is a fact the section has, so a badge left unwired fails loudly here."""

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
        """A section whose model answers a badge role but whose delegate omits it fails here."""
        from amaze.panel import delegates
        for key, expected in EXPECTED_BADGES.items():
            panel = self.activate(key)
            model = getattr(panel, BINDINGS[key]["grid"]).sourceModel()
            for badge, role_name in BADGE_ROLES.items():
                if not role_name or delegates.BADGE[badge].equals or delegates.BADGE[badge].art_for:
                    continue    # no role, or values of a shared one: a model having it says nothing
                if not hasattr(model, role_name):
                    continue
                if badge in expected:
                    continue
                self.assertIn(
                    (key, badge),
                    (("cop", "versions"), ("gradient", "versions")),
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
        """Keyed off `delegates.BADGES`, so a badge added to no section cannot pass unseen."""
        from amaze.panel import delegates
        self.assertEqual(
            {badge.name: badge.role for badge in delegates.BADGES}, BADGE_ROLES,
            "delegates.BADGES and this file disagree about which badges "
            "exist or what they read - a new one needs a role name and a "
            "line per section")


class TheGridIsBoundToItsOwnContext(AreaBindingCase):

    def test_every_section_binds_its_own_four_areas(self):
        for key, expected in BINDINGS.items():
            with self.subTest(section=key):
                panel = self.activate(key)
                actual = self.bound(panel)
                for area in ("grid", "selection", "delegate", "sidebar"):
                    self.assertIs(
                        actual[area], getattr(panel, expected[area]),
                        "%s bound the wrong %s - expected panel.%s. Two "
                        "sections share a delegate instance and two "
                        "share a proxy class, so a wrong binding here "
                        "looks right to an isinstance check and shows up "
                        "as the previous tab's tiles"
                        % (key, area, expected[area]))


class TheSidebarIsBoundToItsOwnContext(AreaBindingCase):

    def test_the_sidebar_has_a_row_selected_after_every_activation(self):
        """`cat_list` keeps no selection across setModel(), so every activation must choose a row."""
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

    CONVERTS = "file"   # the only section that converts, so the only one allowed to leave the bar up

    def test_the_conversion_progress_bar_belongs_to_no_section(self):
        """Every activation hides the conversion bar; File is excluded, as its own work may show it."""
        for key in BINDINGS:
            if key == self.CONVERTS:
                continue
            with self.subTest(section=key):
                panel = self.activate(key)
                panel.texture_progress.setVisible(True)
                panel._section().activate()
                QtWidgets.QApplication.processEvents()
                self.assertTrue(   # isHidden(), not isVisible(): the panel is never shown, so isVisible() is always False
                    panel.texture_progress.isHidden(),
                    "%s activated and left another section's conversion "
                    "bar on screen" % key)

    def test_the_File_section_may_only_show_it_for_its_OWN_work(self):
        """File may leave the bar up only while it has conversions of its own outstanding."""
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

    def test_capture_is_offered_on_every_tab(self):
        """Named, not looked up with a fallback: a pin that can skip is not a pin."""
        button = self.panel.btn_hip_capture
        for key in BINDINGS:
            with self.subTest(section=key):
                self.activate(key)
                self.assertFalse(button.isHidden(), "Capture is hidden on the %s tab" % key)
                self.assertTrue(button.isEnabled(), "Capture is greyed on the %s tab" % key)


class TheCommentsPaneFollowsTheContext(AreaBindingCase):
    """Comments subject per context: asset id, raw path for File rows, uid for a gradient."""

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
    """The online world is parallel, not a view mode, but drives the same four widgets."""

    def test_entering_binds_the_online_models_and_leaving_puts_back_yours(self):
        panel = self.activate("gradient")
        self.addCleanup(self._restore)
        before = self.bound(panel)
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        actual = self.bound(panel)
        for area, name in ONLINE_BINDINGS.items():
            self.assertIs(actual[area], getattr(panel, name),
                          "the online world bound the wrong %s - "
                          "expected panel.%s" % (area, name))
        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()
        after = self.bound(panel)
        for area in ("grid", "selection", "delegate", "sidebar"):
            self.assertIs(
                after[area], before[area],
                "coming back from the online world left the %s on "
                "something else" % area)

    def test_picking_a_source_resets_the_catalogue_ONCE(self):
        """A loaded catalogue answers a source pick with one reset, showing that source."""
        from amaze.core import matx_sources

        panel = self.activate("material")
        self.addCleanup(self._restore)
        online = panel.matx_online_model
        names = [source.name for source in online.sources[:2]]
        for attr in ("_all", "_loaded"):
            self.addCleanup(setattr, online, attr, getattr(online, attr))
        online._generation += 1    # outdates any fetch still in flight, or it lands on the seed ▸p/seeded-catalogue
        online._all = [matx_sources.MatxRecord(
            source=name, uid="%s-%d" % (name, n), title="%s %d" % (name, n),
            category="Metal") for name in names for n in range(3)]
        online._loaded = True
        panel.enter_online_world(names[0])
        QtWidgets.QApplication.processEvents()
        resets = []
        online.modelReset.connect(lambda: resets.append(1))
        panel.open_online_source(names[1])
        self.assertEqual(1, len(resets),
                         "one source pick reset the catalogue %d times"
                         % len(resets))
        self.assertEqual({names[1]}, {online.record(row).source
                                      for row in range(online.rowCount())})

    def test_its_delegate_carries_no_role_the_online_model_lacks(self):
        """Columns follow the active delegate's roles, so the online one carries only online roles."""
        delegate = self.panel.matx_delegate
        model = self.panel.matx_online_model
        for role in ("_versions_role", "_licence_role", "_notes_role",
                     "_active_version_role", "_category_color_role"):
            self.assertFalse(
                getattr(delegate, role, None),
                "the online delegate carries %s, so the grid paints a "
                "column no online record can fill" % role)
        self.assertEqual(model.CategoryRole, delegate._category_role)  # ...and the roles it carries are the online model's, so it cannot pass by carrying none
        self.assertEqual(model.FavoriteRole, delegate._favorite_role)
        self.assertEqual(model.TagRole, delegate._tag_role)

    def test_entering_and_leaving_go_through_ONE_path(self):
        """Entering and leaving run everything `_on_tab_toggled` does, so Capture and Comments follow."""
        panel = self.activate("file")
        self.addCleanup(self._restore)
        self.assertTrue(panel.btn_hip_capture.isEnabled(),
                        "Capture should be offered on the File tab, so "
                        "this test is not set up to prove anything")

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertFalse(
            panel.btn_hip_capture.isEnabled(),
            "Capture is still live in the online world, where no tile "
            "is in the library to keep one")
        self.assertFalse(panel.btn_hip_capture.isHidden(),
                         "Capture left the toolbar online; it greys there")
        self.assertFalse(   # not `assertIsNone(panel._notes_subject())`: with no online rows it is None regardless
            panel.online_context.takes_comments,
            "the online world claims a comment can be written against "
            "an online record, which has no library asset to carry it")


class TheOnlineWorldIsASKEDLikeAnySection(AreaBindingCase):
    """Panel paths ask the online context like any section; `_is_online()` is left for world questions."""

    def test_the_context_declares_every_verb_the_branches_relied_on(self):
        """Every verb a deleted branch relied on is still declared by the online context."""
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

    def test_the_sidebar_still_filters_the_catalogue_when_online(self):
        """Runs the moved `select_category` body by driving the category models directly."""
        from amaze.core import matx_sources

        panel = self.activate("material")
        self.addCleanup(self._restore)
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()

        online = panel.matx_online_model  # seeded via `_all`, the model's cache: the fixture blocks the network, so nothing arrives
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
        self.assertEqual(   # `_filters` is the proxy's own store: MultiFilterProxyModel offers no filter reader
            "Metal",
            panel.matx_sorted_model._filters.get(online.CategoryRole),
            "selecting an online category did not narrow the catalogue, "
            "so the branch moved off the panel without arriving")


class EveryTileDelegateIsSweptByEverySweep(AreaBindingCase):
    """Tile delegates come from one accessor built from the sections, so every sweep reaches each."""

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
        self.assertEqual(
            len(set(id(d) for d in swept)), len(swept),
            "the same delegate is in the list twice, so a sweep does its "
            "work on it twice")


class TheBindingsAreDeclaredNotHandWritten(unittest.TestCase):
    """Every section activates through its own activate(); the online world enters via the panel."""

    _PUT_BACKS = ("preserving_selection_and_current", "keep_editor_focus")    # ▸p/amaze-follows-houdini

    def test_no_import_door_puts_the_artist_back(self):
        """An import leaves the new node selected and the editors where Houdini puts them."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = []
        for name in ("panel.py", "sections.py", "dragdrop_widgets.py"):
            with open(os.path.join(root, "panel", name), encoding="utf-8") as fh:
                source = fh.read()
            for wrapper in self._PUT_BACKS:
                if wrapper in source:
                    found.append("%s uses %s" % (name, wrapper))
        self.assertEqual(
            [], found,
            "an import door puts the selection or the network editors "
            "back, which undoes what Houdini does for a new node: %s" % found)


class TheReleaseVerbsLiveOnTheirSections(unittest.TestCase):
    """Every release verb a drop rule names is callable on the section that declares it."""

    def test_every_rule_named_verb_is_defined_by_its_section(self):
        """Every DROP / DROP_BY_KIND named verb must be callable on its declaring section class."""
        from amaze.panel import sections
        missing = []
        for cls in sections.SECTION_CLASSES:
            rules = []
            if getattr(cls, "DROP", None) is not None:
                rules.append(cls.DROP)
            rules.extend(getattr(cls, "DROP_BY_KIND", {}).values())
            names = {name for rule in rules for name in (
                rule.on_node, rule.on_space, rule.resolve,
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


class EveryDoubleClickReachesTheClickWalker(unittest.TestCase):
    """A double-click is the click walker's in every section, one added tomorrow included."""

    def test_every_section_and_a_new_one_reach_the_walker(self):
        from amaze.panel import sections

        class _Panel:
            def __init__(self):
                self.walked = []

            def click_on_row(self, section, index, payload=None):
                self.walked.append((section, index))

        class _NewSection(sections.Section):    # declares no double-click of its own
            key = "new"

        for cls in sections.SECTION_CLASSES + (_NewSection,):
            with self.subTest(section=cls.__name__):
                panel = _Panel()
                section = cls(panel)
                index = object()
                section.double_click(index)
                self.assertEqual([(section, index)], panel.walked,
                                 "%s's double-click never reached the walker" % cls.__name__)


if __name__ == "__main__":
    unittest.main()
