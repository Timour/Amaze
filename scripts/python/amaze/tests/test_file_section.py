"""The File section merge's OWN inventions - the one-time prefs migration into the file_* quartet, the tab introducing itself once, `kind_for` routing, Copy Path's Houdini spelling, the OS-icon fallback, the per-kind double-click dispatch, and the hip drag (loads outside the panel, silent inside); the wider machinery stays pinned in test_hip_section, test_folder_sections, test_tile_icons and test_drag_gesture."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import file_library  # noqa: E402
from amaze.core import locations as locations_mod  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.prefs import prefs as prefs_module  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


def _prefs_with_settings(testcase, settings: dict, tag_favourites=True):
    """A Prefs whose settings.json holds exactly `settings`, loaded - `library_user` goes IN the file because load() reads it back off disk (assigned-after is overwritten), and the favourites copy is tagged at this one door; `tag_favourites=False` deliberately writes the PRE-TAG shape an upgrading machine's settings.json actually holds."""
    home = tempfile.mkdtemp(prefix="amaze_file_prefs_")
    testcase.addCleanup(shutil.rmtree, home, ignore_errors=True)
    settings = dict(settings)
    settings.setdefault("library_user", test_support.FIXTURE_USER)
    if tag_favourites and settings.get("library_user"):
        from amaze.core import keyed_store as _ks
        mine = settings["library_user"] + _ks.USER_SEP
        settings["file_favorites"] = [
            path if _ks.USER_SEP in path else mine + path
            for path in settings.get("file_favorites", ())]
    with open(os.path.join(home, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump(settings, handle)
    p = prefs_module.Prefs()
    p.path = home
    p.load()
    return p


def _location_prefs(testcase, settings, tag_favourites=True):
    """A Prefs over a fresh temp library, with `settings` loaded - the library is assigned into the settings BEFORE load(), because the first locations read runs the migration and a library assigned after is too late; the redirect assert below stops every test here from writing whatever library the settings actually name."""
    library = tempfile.mkdtemp(prefix="amaze_loc_library_")
    testcase.addCleanup(shutil.rmtree, library, ignore_errors=True)
    data = dict(settings)
    data["directory"] = library
    locations_mod.forget()
    testcase.addCleanup(locations_mod.forget)
    prefs = _prefs_with_settings(testcase, data,
                                 tag_favourites=tag_favourites)
    library = prefs.dir    # load() normalises the path; compare the resolved form
    testcase.assertTrue(
        os.path.normcase(os.path.normpath(library)).startswith(    # normcase+normpath BOTH sides: prefs.dir answers the Houdini spelling, gettempdir() the platform's own
            os.path.normcase(os.path.normpath(tempfile.gettempdir()))),
        "the fixture is pointed at %r" % (library,))
    return prefs, library


class TheFileTabIntroducesItselfOnceTest(unittest.TestCase):
    """A settings file from before the File section gains the tab once, and turning it off then sticks."""

    def test_the_file_tab_introduces_itself_once(self):
        old = {"enabled_sections": ["material", "code"]}
        p = _prefs_with_settings(self, old)
        self.assertIn("file", p.enabled_sections,
                      "existing users never see the File tab")
        # Turning it off then sticks - the seen-marker holds.
        p.enabled_sections = ["material", "code"]
        p.save()
        q = prefs_module.Prefs()
        q.path = p.path
        q.load()
        self.assertNotIn(
            "file", q.enabled_sections,
            "disabling the File tab does not stick - it reintroduces "
            "itself on every launch")


class LocationsFollowTheLibraryTest(unittest.TestCase):
    """The locations and File favourites move into the library and settings.json keeps the copy - REAL_SHAPE is shaped on the real settings measured 2026-08-05, deliberately keeping two locations carrying nothing but registration and one `show_all: False` override, the two cases a decoration-table composition or a falsy-dropping normaliser silently loses."""

    REAL_SHAPE = {
        "directory": "",
        "file_folders": ["/tex/img/", "/tex/bokeh/", "/photo/2023/",
                         "/models/obj/", "/houdini/exercise/", "/tex/hdr/"],
        "file_favorites": ["/tex/hdr/017.hdr", "/houdini/exercise/a.hiplc"],
        "file_location_records": {    # the RECORD is the one home; the retired decoration-table spellings never come back
            "/tex/img/": {"registered": True, "recursive": True},
            "/tex/bokeh/": {"registered": True, "recursive": True,
                            "name": "Bokeh files"},
            "/photo/2023/": {"registered": True, "recursive": True,
                             "color": "#134d4d"},
            "/models/obj/": {"registered": True, "recursive": True,
                             "show_all": False},
            "/houdini/exercise/": {"registered": True},
            "/tex/hdr/": {"registered": True},
        },
    }

    def _prefs(self, settings=None, tag_favourites=True):
        return _location_prefs(self, settings or self.REAL_SHAPE,
                               tag_favourites=tag_favourites)

    def test_every_location_arrives_field_for_field(self):
        prefs, _lib = self._prefs()
        self.assertEqual(self.REAL_SHAPE["file_folders"],
                         list(prefs.file_folders),
                         "the registered list did not survive the move, "
                         "or its order changed")
        self.assertEqual(
            {"registered": True, "name": "Bokeh files", "recursive": True},
            locations_mod.record(prefs, "/tex/bokeh/"))
        self.assertEqual(
            {"registered": True, "color": "#134d4d", "recursive": True},
            locations_mod.record(prefs, "/photo/2023/"))
        self.assertEqual(
            {"registered": True, "show_all": False, "recursive": True},
            locations_mod.record(prefs, "/models/obj/"),
            "a Show All Files override set to FALSE was dropped as "
            "falsy, which turns hidden files back on")
        self.assertEqual(sorted(self.REAL_SHAPE["file_favorites"]),
                         sorted(prefs.file_favorites))

    def test_a_location_with_no_decoration_still_arrives(self):
        """Registration alone, no decoration - the case a four-table composition could not represent."""
        prefs, _lib = self._prefs()
        self.assertEqual({"registered": True},
                         locations_mod.record(prefs, "/tex/hdr/"))
        self.assertIn("/houdini/exercise/", prefs.file_folders)

    def test_it_writes_the_two_files_and_marks_itself_done(self):
        prefs, library = self._prefs()
        # The first locations READ is the trigger - a bare load() never writes the library.
        locations_mod.registered_paths(prefs)
        with open(os.path.join(library, "locations.json"),
                  encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertIn("locations", written,
                      "the payload key is missing, so the store reads "
                      "its own file as the wrong file next launch")
        self.assertEqual(6, len(written["locations"]))
        self.assertTrue(os.path.exists(
            os.path.join(library, "favourites.json")))
        self.assertTrue(prefs.data.get(locations_mod.MIGRATED_KEY))

    def test_a_copy_written_before_the_tag_loses_its_stars(self):
        """An UNTAGGED entry in the settings copy is dropped, never adopted - deliberately ONE rule for an ownerless favourite, in the copy exactly as in the library store."""
        prefs, _lib = self._prefs(
            dict(self.REAL_SHAPE, file_favorites=["/tex/hdr/017.hdr"]),
            tag_favourites=False)
        self.assertEqual([], list(prefs.file_favorites),
                         "a star from before the tag was adopted by "
                         "whoever opened the library")

    def test_the_locations_land_even_when_the_favourites_have_no_owner(self):
        """One migration half cannot refuse on behalf of the other: a favourites half that finds nobody defers ALONE, the locations still land, and the marker stays unset so the deferral retries."""
        from unittest import mock
        from amaze.core import keyed_store
        real_update = keyed_store.Store.update

        def refuse_favourites(store, values):
            if store.spec.filename == keyed_store.FAVOURITES:
                return keyed_store.Written(False, keyed_store.REASON_NO_USER)
            return real_update(store, values)

        with mock.patch.object(keyed_store.Store, "update",    # patched from the START: the fixture's own first locations read can migrate, and deleting the files after would hit the .bak tier's BLIND refusal instead of the branch under test
                               refuse_favourites):
            prefs, library = self._prefs()
            result = locations_mod.migrate(prefs)    # marker unset, so this re-runs and answers with the state

        self.assertEqual("deferred", result.get("state"),
                         "a favourites half with no owner refused the "
                         "whole migration")
        with open(os.path.join(library, "locations.json"),
                  encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(6, len(written["locations"]),
                         "the locations half did not land, so the "
                         "sidebar stays empty until somebody is picked")
        self.assertFalse(
            prefs.data.get(locations_mod.MIGRATED_KEY),
            "marked done with the favourites still unmigrated - the old "
            "keys stop being read and the stars are gone for good")

    def test_the_copies_ride_the_block_and_the_five_are_gone(self):
        """The copies persist under the active user's block, and the retired decoration-table spellings are never written again."""
        prefs, _lib = self._prefs()
        prefs.save()
        with open(os.path.join(prefs.path, "settings.json"),
                  encoding="utf-8") as handle:
            on_disk = json.load(handle)
        block = on_disk["users"][test_support.FIXTURE_USER]
        self.assertEqual(6, len(block["file_folders"]))
        self.assertEqual(6, len(block["file_location_records"]))
        self.assertEqual(
            "Bokeh files",
            block["file_location_records"]["/tex/bokeh/"].get("name"))
        for retired in ("file_folder_names", "file_folder_colors",
                        "file_folder_show_all", "file_recursive_folders",
                        "file_include_subfolders", "file_folders",
                        "file_favorites", "file_location_records"):
            self.assertNotIn(retired, on_disk,
                             "%s is still written flat" % retired)

    def test_the_second_machine_keeps_its_own_folders_and_gains_the_others(self):
        """A second machine's settings.json never travels, so its keys are folders nothing has carried anywhere: the merge is ADOPT-ONLY - it keeps its own, gains the first machine's, and a store taken as-is would have emptied that sidebar with the only record of the loss just overwritten."""
        first, library = self._prefs()          # the machine that got there first
        self.assertEqual(6, len(first.file_folders))

        second = _prefs_with_settings(self, {    # its own settings, the SAME library
            "directory": library,
            "file_folders": ["/laptop/only/", "/tex/img/"],
            "file_favorites": ["/laptop/only/shot.exr"],
            "file_location_records": {
                "/laptop/only/": {"registered": True,
                                  "name": "Laptop scratch"},
                "/tex/img/": {"registered": True},
            },
        })
        self.assertIn("/laptop/only/", second.file_folders,    # no explicit migrate(): the FIRST LOCATIONS READ runs it - asserting the END state, not a return value
                      "the second machine's own registered folder was "
                      "discarded when it met a library that already had "
                      "locations in it")
        self.assertTrue(second.data.get(locations_mod.MIGRATED_KEY))
        self.assertEqual(
            "Laptop scratch",
            locations_mod.record(second, "/laptop/only/").get("name"),
            "its label did not come with it")
        self.assertIn("/tex/bokeh/", second.file_folders,
                      "the first machine's folders did not arrive")
        self.assertIn("/laptop/only/shot.exr", second.file_favorites)
        self.assertIn("/tex/hdr/017.hdr", second.file_favorites)
        self.assertEqual(    # /tex/img/ is registered on BOTH and must not double
            1, list(second.file_folders).count("/tex/img/"),
            "a folder both machines had registered arrived twice")

    def test_a_lost_store_is_re_seeded_from_the_copy(self):
        """A locations.json deleted or restored away on a migrated machine used to leave the sidebar EMPTY - the code trusted an empty store over its own copy, and it happened for real."""
        prefs, library = self._prefs()
        self.assertEqual(6, len(prefs.file_folders))

        os.remove(os.path.join(library, "locations.json"))
        locations_mod.forget()

        self.assertTrue(locations_mod.showing_last_known(prefs),    # the .bak tier proves the file WAS here, so the store answers BLIND and refuses writes - refuse-over-overwrite, not a fault
                        "a store that cannot be read is not reported as "
                        "such, so the sidebar cannot mark it")
        self.assertEqual(
            self.REAL_SHAPE["file_folders"], list(prefs.file_folders),
            "the store was empty and the sidebar went empty with it, "
            "although settings.json still held every folder")
        self.assertEqual(
            {"registered": True, "name": "Bokeh files", "recursive": True},
            locations_mod.record(prefs, "/tex/bokeh/"),
            "the copy lost the per-location facts")

    def test_a_library_with_no_store_at_all_is_re_seeded(self):
        """The FRESH shape - a new or replaced library, nothing says a store was ever here - re-seeds from the copy, or a migrated machine would show an empty sidebar over a writable library forever."""
        prefs, _library = self._prefs()
        fresh = tempfile.mkdtemp(prefix="amaze_loc_newlib_")
        self.addCleanup(shutil.rmtree, fresh, ignore_errors=True)
        locations_mod.forget()
        prefs.dir = fresh

        self.assertEqual(self.REAL_SHAPE["file_folders"],
                         list(prefs.file_folders),
                         "a library with no store answered empty rather "
                         "than re-seeding from the copy")
        self.assertTrue(
            os.path.exists(os.path.join(fresh, "locations.json")),
            "it read from the copy but never wrote the store, so the "
            "next write would start from nothing")

    def test_removing_every_folder_still_sticks(self):
        """`keep_last_known` writes the copy FROM the store, so removing the last location empties both - a rule that re-seeded on an empty store alone would make removing every folder impossible."""
        prefs, _library = self._prefs()
        for path in list(prefs.file_folders):
            prefs.remove_file_folder(path)
        locations_mod.forget()
        self.assertEqual([], list(prefs.file_folders),
                         "removing every location did not stick - they "
                         "came back from the copy")

    def test_a_migration_that_does_not_reproduce_refuses_to_mark(self):
        """A store whose normaliser cannot hold what went in leaves the marker UNSET so the old keys stay the truth and the next launch retries - the acceptance test is the end state, not that the write ran."""
        prefs, _lib = self._prefs({
            "file_folders": ["/a/"],
            "file_favorites": [],
            "file_location_records": {"/a/": {"registered": True}}})
        prefs.data[locations_mod.MIGRATED_KEY] = False
        locations_mod.forget()
        real_normalise = locations_mod.SPEC.normalise
        locations_mod.SPEC.normalise = lambda value: {}    # a quietly-dropping normaliser is the real failure shape: tile_icons.normalise really drops an unshipped icon
        try:
            result = locations_mod.migrate(prefs)
        finally:
            locations_mod.SPEC.normalise = real_normalise
        self.assertEqual("refused", result["state"],
                         "a migration that reproduced nothing reported "
                         "success")
        self.assertFalse(prefs.data.get(locations_mod.MIGRATED_KEY),
                         "the marker was set although the stores do not "
                         "match, so the old keys will never be read again")

    def test_an_unreachable_library_shows_the_last_known_list(self):
        """DECIDED: the last known locations still list, marked unreachable - the File section is the browser you most want working when a drive is not mounted."""
        prefs, library = self._prefs()
        locations_mod.forget()
        prefs.dir = os.path.join(library, "not-mounted")

        self.assertTrue(locations_mod.showing_last_known(prefs),
                        "an unreachable library is not reported as such, "
                        "so the sidebar cannot mark it")
        self.assertEqual(self.REAL_SHAPE["file_folders"],
                         list(prefs.file_folders),
                         "the locations vanished when the library went "
                         "away - the copy exists precisely for this")
        self.assertEqual(
            {"registered": True, "name": "Bokeh files", "recursive": True},
            locations_mod.record(prefs, "/tex/bokeh/"),
            "the copy lost the per-location facts")
        self.assertEqual(sorted(self.REAL_SHAPE["file_favorites"]),
                         sorted(prefs.file_favorites))

    def test_with_no_library_at_all_a_write_still_lands(self):
        """The File section still works with no library configured - and an empty `dir` must never turn into a store written beside the current directory."""
        prefs = _prefs_with_settings(self, {"file_folders": ["/a/"],
                                            "file_favorites": []})
        self.assertEqual("", prefs.dir)
        prefs.add_file_folder("/b/")
        prefs.add_file_favorite("/b/pic.exr")
        self.assertEqual(["/a/", "/b/"], list(prefs.file_folders))
        self.assertEqual(["/b/pic.exr"], list(prefs.file_favorites))
        self.assertFalse(
            os.path.exists("locations.json"),
            "a store was written next to the current directory")


class LocationsArePerUserTest(unittest.TestCase):
    """The locations are user-tagged: each user of a shared library registers their own folders, pre-tag rows adopt into whoever opens the library, and a machine with nobody picked serves its settings copy instead of an empty sidebar while the ASK dialog waits."""

    OTHER = "0f0e0d0c0b0a09080706050403020100"

    PRE_TAG_ROWS = {    # a pre-tag locations.json - what an upgrading machine's library holds on first open (name, show_all and recursive; colour is exercised in REAL_SHAPE)
        "/tex/img/": {"registered": True, "recursive": True},
        "/tex/bokeh/": {"registered": True, "name": "Bokeh files"},
        "/models/obj/": {"registered": True, "show_all": False},
    }

    SETTINGS = {
        "directory": "",
        locations_mod.MIGRATED_KEY: True,
        "file_folders": ["/tex/img/", "/tex/bokeh/", "/models/obj/"],
        "file_location_records": dict(PRE_TAG_ROWS),
        "file_favorites": [],
    }

    def _upgrading(self, library_user=test_support.FIXTURE_USER):
        """A machine that migrated before the tag: marker set, library holding an untagged store, the copy in step with it."""
        settings = dict(self.SETTINGS, library_user=library_user)
        prefs, library = _location_prefs(self, settings)
        with open(os.path.join(library, "locations.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"locations": dict(self.PRE_TAG_ROWS)}, handle)
        locations_mod.forget()
        return prefs, library

    def _stored_keys(self, library):
        with open(os.path.join(library, "locations.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)["locations"]

    def test_the_locations_spec_declares_the_tag(self):
        self.assertTrue(
            locations_mod.SPEC.user_tagged,
            "the locations spec lost its user tag - every test in this "
            "class is about behaviour that flag switches on")

    def test_pre_tag_rows_adopt_into_the_opener_field_for_field(self):
        prefs, library = self._upgrading()
        self.assertEqual(self.SETTINGS["file_folders"],
                         list(prefs.file_folders),
                         "the pre-tag rows did not adopt, or the order "
                         "moved off the copy's")
        stored = self._stored_keys(library)
        from amaze.core import keyed_store
        mine = test_support.FIXTURE_USER + keyed_store.USER_SEP
        self.assertEqual(
            len(self.PRE_TAG_ROWS), len(stored),
            "rows were lost or invented in the adoption")
        self.assertTrue(
            all(key.startswith(mine) for key in stored),
            "the file still holds untagged spellings, or rows landed "
            "under someone else")
        self.assertEqual(
            {"registered": True, "name": "Bokeh files"},
            locations_mod.record(prefs, "/tex/bokeh/"))
        self.assertEqual(
            {"registered": True, "show_all": False},
            locations_mod.record(prefs, "/models/obj/"),
            "a Show All Files override set to FALSE was lost in the "
            "adoption")

    def test_one_users_folders_are_not_anothers(self):
        prefs, _library = self._upgrading()
        self.assertEqual(3, len(prefs.file_folders))
        prefs.library_user = self.OTHER
        locations_mod.forget()
        self.assertEqual(
            [], list(prefs.file_folders),
            "a second user sees the first user's registered folders")

    def test_nobody_picked_serves_the_copy_and_refuses_writes(self):
        prefs, library = self._upgrading(library_user="")
        before = self._stored_keys(library)
        self.assertTrue(
            locations_mod.showing_last_known(prefs),
            "a per-user store with nobody picked claims it can answer")
        self.assertEqual(self.SETTINGS["file_folders"],
                         list(prefs.file_folders),
                         "the sidebar went empty during the ASK window "
                         "although the copy holds every folder")
        self.assertEqual(
            {"registered": True, "name": "Bokeh files"},
            locations_mod.record(prefs, "/tex/bokeh/"),
            "the copy lost the per-location facts")

        from amaze.core import keyed_store
        written = locations_mod.set_record(
            prefs, "/nobody/", {"registered": True})
        self.assertFalse(written)
        self.assertEqual(keyed_store.REASON_NO_USER, written.reason)
        self.assertNotIn("/nobody/", list(prefs.file_folders),
                         "a write with nobody picked landed somewhere "
                         "a picked user will never see")
        self.assertEqual(
            before, self._stored_keys(library),
            "a refused write still moved the store, so the pre-tag "
            "rows are gone before anyone could adopt them")
        self.assertEqual(
            dict(self.PRE_TAG_ROWS),
            dict(prefs.last_known_records),
            "the no-user window blanked the settings copy - the exact "
            "wipe the mirror guard exists to stop")

    def test_picking_a_user_mid_session_finishes_the_job(self):
        prefs, library = self._upgrading(library_user="")
        self.assertTrue(locations_mod.showing_last_known(prefs))
        prefs.library_user = test_support.FIXTURE_USER
        self.assertFalse(
            locations_mod.showing_last_known(prefs),
            "picking a user did not bring the store back - the no-user "
            "state was parked for the session")
        self.assertEqual(self.SETTINGS["file_folders"],
                         list(prefs.file_folders))
        from amaze.core import keyed_store
        mine = test_support.FIXTURE_USER + keyed_store.USER_SEP
        self.assertTrue(
            all(key.startswith(mine) for key in self._stored_keys(library)),
            "the adoption did not run when the user arrived")

    def test_a_removal_takes_every_users_registration_with_it(self):
        prefs, library = self._upgrading()
        self.assertIn("/tex/bokeh/", prefs.file_folders)
        prefs.library_user = self.OTHER
        locations_mod.forget()
        locations_mod.register(prefs, "/tex/bokeh/")
        self.assertIn("/tex/bokeh/", prefs.file_folders)

        from amaze.core import keyed_store
        keyed_store.retire_prefix(prefs, "/tex/bokeh/")
        self.assertNotIn("/tex/bokeh/", prefs.file_folders)
        prefs.library_user = test_support.FIXTURE_USER
        locations_mod.forget()
        self.assertNotIn(
            "/tex/bokeh/", prefs.file_folders,
            "a removal cleared only the removing user's registration - "
            "the folder survives for everyone else and comes back")

    def test_the_mirror_never_blanks_the_copy_with_nobody_picked(self):
        """A scoped read with nobody picked answers {} meaning NO ANSWER, not no locations - driven directly because every write door refuses before the mirror; this is the belt for a caller that forgets to."""
        prefs, _library = self._upgrading(library_user="")
        locations_mod._sync_mirror(prefs)
        self.assertEqual(
            dict(self.PRE_TAG_ROWS), dict(prefs.last_known_records),
            "the mirror blanked the copy from a scoped read that "
            "answers nothing - the fallback died while it was serving")

    def test_the_seed_migration_defers_whole_with_nobody_picked(self):
        settings = {"directory": "", "library_user": "",
                    "file_folders": ["/a/"], "file_favorites": [],
                    "file_location_records": {
                        "/a/": {"registered": True}}}
        prefs, library = _location_prefs(self, settings)
        result = locations_mod.migrate(prefs)
        self.assertEqual("deferred", result.get("state"),
                         "a migration with nobody to own the rows "
                         "reported a refusal, which nothing retries")
        self.assertFalse(prefs.data.get(locations_mod.MIGRATED_KEY),
                         "the marker is set, so the old keys will "
                         "never be read again")
        self.assertFalse(
            os.path.exists(os.path.join(library, "locations.json")),
            "half a migration landed with nobody picked")


class KindRouterTest(unittest.TestCase):
    """kind_for is the router every per-type behaviour hangs off, fed by the three sections' own recognisers - one source each."""

    def test_each_kind_routes_to_its_section_of_origin(self):
        for name, kind in (
                ("a.hip", "hip"), ("b.HIPLC", "hip"), ("c.hipnc", "hip"),
                ("d.png", "image"), ("e.EXR", "image"), ("f.hdr", "image"),
                ("m.rat", "image"),    # Houdini's own texture format - sips fails cleanly on it, the iconvert fallback converts it
                ("n.dng", "image"), ("o.DNG", "image"),    # camera raw macOS decodes natively (probed: sips converts a real DNG in ~2.3s)
                ("g.bgeo.sc", "geometry"), ("h.obj", "geometry"),
                ("i.usd", "geometry"),
                ("j.txt", "other"), ("k.bvh", "other"), ("noext", "other"),
                ("l.hip.bak", "other")):
            self.assertEqual(kind, file_library.kind_for(name), name)


class ScenePathsAreSpelledPerPreferenceTest(unittest.TestCase):
    """Every path Amaze writes INTO THE SCENE goes through _scene_path (the Write Paths As preference) - the texture funnel, the geometry loader and the drag payload all once wrote raw absolutes; the texture-funnel case is pinned in DropFilePathOnNodeTest."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def test_the_geometry_loader_writes_the_spelled_path(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_pathtest_dest")
        self.addCleanup(geo.destroy)
        self.panel._import_geo_in_context(
            home + "/models/amaze_spelling.obj", geo)
        loaders = [n for n in geo.children() if n.type().name() == "file"]
        self.assertTrue(loaders, "no loader SOP was created")
        self.assertEqual(
            "$HOME/models/amaze_spelling.obj",
            loaders[0].parm("file").rawValue(),
            "the geometry import writes the raw absolute path")

    def test_the_drag_payload_is_the_spelled_text_and_nothing_else(self):
        """ONE flavour, the spelled text: a file URL is an OS open-this handle Houdini honoured - released outside a field it OFFERED to clear the scene, and inside one it BEAT the spelled text, which is why drops wrote absolute paths."""
        home = self._home()
        raw = home + "/textures/amaze_spelling.png"
        mime = self.panel.thumblist._file_drag_mime(self.panel, raw)
        self.assertEqual("$HOME/textures/amaze_spelling.png",
                         mime.text(),
                         "the drag's text flavour is not spelled per "
                         "the preference")
        self.assertFalse(mime.hasUrls(),
                         "the drag carries a file URL again - Houdini "
                         "reads it as open-this-file")

    def test_no_raw_parm_set_of_a_path_remains(self):
        panel_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(panel_py, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "parm.set(path)", source,
            "a raw parm.set of a path returned to panel.py - scene "
            "paths go through _scene_path")


class DropFilePathOnNodeTest(unittest.TestCase):
    """The release-on-a-node verb: the node's FIRST file parameter takes the SPELLED path, and a node with no file parameter refuses with a dialog-free False so the gesture can show its own miss - dispatch pinned in test_drag_gesture."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def _index_for(self, path):
        import types
        return types.SimpleNamespace(data=lambda role: path)

    def test_the_first_file_parm_takes_the_spelled_path(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_droptest")
        self.addCleanup(geo.destroy)
        loader = geo.createNode("file")
        self.assertTrue(self.panel.sections["file"].drop_file_path_on_node(
            self._index_for(home + "/textures/amaze_drop.png"), loader))
        self.assertEqual(
            "$HOME/textures/amaze_drop.png",
            loader.parm("file").rawValue(),
            "the hand-over wrote a raw absolute path")

    def test_a_node_with_no_file_parm_refuses_without_a_dialog(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_droptest2")
        self.addCleanup(geo.destroy)
        bare = geo.createNode("null")
        self.assertFalse(
            self.panel.sections["file"].drop_file_path_on_node(
                self._index_for(home + "/x.png"), bare),
            "a node with nothing to take the path claimed success")


class CreationRuleTest(unittest.TestCase):
    """A release on empty network space (and a no-selection double-click) creates the payload's carrier wherever the network can hold one and refuses with False where it cannot - the type existing in the network's child category IS the capability test."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        hou.clearAllSelected()

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def _matnet(self):
        net = hou.node("/obj").createNode("matnet")
        self.addCleanup(net.destroy)
        return net

    def _geo(self):
        net = hou.node("/obj").createNode("geo")
        self.addCleanup(net.destroy)
        return net

    def _index_for(self, path, kind=None):
        import types
        from amaze.core import file_library
        roles = {file_library.FileFiles.PathRole: path}
        if kind is not None:
            roles[file_library.FileFiles.KindRole] = kind
        return types.SimpleNamespace(
            data=lambda role: roles.get(role, path),
            isValid=lambda: True)

    def test_an_image_becomes_a_mtlximage_with_the_spelled_path(self):
        from amaze.helpers import helpers

        home = self._home()
        net = self._matnet()
        self.assertTrue(self.panel.sections["file"].create_image_node_in(
            self._index_for(home + "/textures/amaze_create.png"), net))
        children = net.children()
        self.assertEqual(1, len(children), "exactly one carrier")
        self.assertIn("mtlximage", children[0].type().name())
        self.assertEqual(
            "$HOME/textures/amaze_create.png",
            helpers.find_file_parm(children[0]).rawValue(),
            "the carrier holds a raw absolute path")

    def test_a_sop_network_refuses_the_image_carrier(self):
        net = self._geo()
        self.assertFalse(self.panel.sections["file"].create_image_node_in(
            self._index_for(self._home() + "/x.png"), net))
        self.assertEqual((), net.children(),
                         "a refusing network gained a child anyway")

    def test_a_gradient_becomes_the_mtlx_ramp_carrier(self):
        from amaze.helpers import helpers

        net = self._matnet()
        index = self.panel.gradient_sorted_model.index(0, 0)
        self.assertTrue(index.isValid(),
                        "premise: the fixture has gradients")
        self.assertTrue(self.panel.sections["gradient"].create_gradient_node_in(index, net))
        children = net.children()
        self.assertEqual(1, len(children))
        self.assertIn("hmtlxrampc", children[0].type().name())
        self.assertIsNotNone(
            helpers.find_color_ramp_parm(children[0]),
            "the carrier has no ramp to have taken the gradient")

    def test_a_vex_snippet_becomes_a_wrangle_in_a_sop_network(self):
        from amaze.helpers import helpers

        net = self._geo()
        index = self.panel.code_sorted_model.index(0, 0)
        self.assertTrue(index.isValid(),
                        "premise: the fixture has snippets")
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.assertTrue(self.panel.sections["code"].create_code_node_in(index, net))
        children = net.children()
        self.assertEqual(1, len(children))
        self.assertIn("attribwrangle", children[0].type().name())
        self.assertEqual(
            asset.code, helpers.find_code_parm(children[0]).eval(),
            "the wrangle does not carry the snippet")

    def test_a_vop_network_refuses_a_vex_snippet(self):
        net = self._matnet()
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.assertFalse(self.panel.sections["code"].create_code_node_in(index, net))
        self.assertEqual((), net.children())

    def _with_view_networks(self, networks):
        self.panel._view_create_networks = lambda: list(networks)
        self.addCleanup(
            lambda: self.panel.__dict__.pop("_view_create_networks", None))

    def test_a_positioned_carrier_never_auto_places(self):
        """A given position IS the placement - moveToGoodPosition may shove unconnected siblings aside, so it runs only as the no-position fallback."""
        from unittest import mock
        net = self._matnet()
        spot = hou.Vector2(-3.5, -2.25)
        with mock.patch.object(hou.Node, "moveToGoodPosition") as auto:
            ok = self.panel.sections["file"].create_image_node_in(
                self._index_for(self._home() + "/x.png"), net,
                position=spot)
        self.assertTrue(ok)
        auto.assert_not_called()
        child = net.children()[0]
        from amaze.helpers import helpers
        anchor = helpers.centred_on(spot)
        self.assertEqual((anchor.x(), anchor.y()),
                         (child.position().x(), child.position().y()),
                         "the carrier is not centred on the release "
                         "point")

    def test_the_release_position_stays_in_its_own_space(self):
        """A release over a container resolves INSIDE it while the cursor stays in the OUTER editor's plane, so the resolver answers only when the editor under the cursor shows the destination network itself."""
        from unittest import mock
        import types
        inside = self._matnet()
        outer = self._geo()
        editor = types.SimpleNamespace(
            type=lambda: hou.paneTabType.NetworkEditor,
            pwd=lambda: outer,
            cursorPosition=lambda: hou.Vector2(9.0, 9.0))
        from amaze.core import dragengine
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               return_value=editor):
            self.assertIsNone(
                self.panel._release_position_in(inside),
                "a foreign editor's coordinates crossed into the "
                "destination network")
            got = self.panel._release_position_in(outer)
        self.assertEqual((9.0, 9.0), (got.x(), got.y()))

    def test_a_creation_never_steals_the_selection(self):
        """Houdini tags newborns selected and current, which scrolled the editor and hijacked the NEXT double-click - a door leaves the artist's selection exactly as it was."""
        sop = self._geo()
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        hou.clearAllSelected()
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual(1, len(sop.children()), "premise: created")
        self.assertEqual(
            (), hou.selectedNodes(),
            "the newborn carrier stayed selected - it will hijack "
            "the next double-click")

    def test_a_menu_copy_to_leaves_the_artists_scene_state_alone(self):
        """The menu's Copy To imports into /mat and the artist's scene selection survives it exactly as it survives a drop - the verb's wrapper puts the artist back."""
        net = self._geo()
        self._with_view_networks([net])
        keeper = net.createNode("box", "the_artists_own")
        keeper.setSelected(True, clear_all_selected=True)
        proxy = self.panel.material_sorted_model
        index = None
        for row in range(proxy.rowCount()):
            candidate = proxy.index(row, 0)
            source = proxy.mapToSource(candidate)
            asset = self.panel.material_model.assets[source.row()]
            if str(getattr(asset, "renderer", "")):
                index = candidate
                break
        if index is None:
            self.skipTest("no fixture material carries a renderer")
        self.panel.material_selection_model.select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect
            | QtCore.QItemSelectionModel.Rows)
        mat_net = hou.node("/mat")
        before = len(mat_net.children())
        self.panel.sections["material"].menu_copy_to(
            (index,), index, payload="mat")
        if len(mat_net.children()) == before:
            self.skipTest("the fixture material did not import")
        self.assertEqual(
            (keeper,), hou.selectedNodes(),
            "a menu Copy To moved the artist's scene selection")

    def test_a_refused_click_is_absorbed_like_a_refused_drop(self):
        """Houdini answering no (a locked network) must not escape the click dispatcher as a slot crash - the drag dispatch already absorbs exactly this class and says why."""
        from amaze.panel import sections as sections_module

        class RefusingSection:
            key = "refusing"
            DROP = sections_module.DropRule(
                click_resolve="refuse_for_the_test")

            def refuse_for_the_test(self, _index):
                raise hou.PermissionError(
                    "Cannot create a node inside a locked asset")

        index = self.panel.code_sorted_model.index(0, 0)
        self.panel.click_on_row(RefusingSection(), index)

    def test_a_genuine_crash_still_escapes_the_click_dispatcher(self):
        """Only the permission class is absorbed - a programming error still crashes where it can be seen."""
        from amaze.panel import sections as sections_module

        class CrashingSection:
            key = "crashing"
            DROP = sections_module.DropRule(
                click_resolve="crash_for_the_test")

            def crash_for_the_test(self, _index):
                raise RuntimeError("a real defect")

        index = self.panel.code_sorted_model.index(0, 0)
        with self.assertRaises(RuntimeError):
            self.panel.click_on_row(CrashingSection(), index)

    def test_the_preserving_helper_restores_what_was(self):
        from amaze.helpers import helpers
        net = self._geo()
        a = net.createNode("box")
        b = net.createNode("sphere")
        hou.clearAllSelected()
        a.setSelected(True)
        with helpers.preserving_selection_and_current():
            a.setSelected(False)
            b.setSelected(True)
        self.assertEqual((a,), hou.selectedNodes(),
                         "the block did not put the selection back")

    def test_the_ghost_promises_what_the_drop_delivers(self):
        """The outline draws the carrier the space door WOULD create, read from the same declaration the creator builds from - two separate answers would let the ghost promise a wrangle and deliver nothing."""
        from amaze.panel import dragdrop_widgets, sections as sections_mod
        sop = self._geo()
        vop = self._matnet()
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        rule = sections_mod.SECTION_INDEX["code"].DROP
        promised = dragdrop_widgets.GridGestureMixin._ghost_type(    # the index is HANDED IN as the live drag hands it - a fixture-planted attribute once proved a ghost production never had
            self.panel, rule, "code", sop, index)
        self.assertTrue(self.panel.sections["code"].create_code_node_in(index, sop))
        made = [c for c in sop.children() if "wrangle" in c.type().name()]
        self.assertEqual(promised, made[0].type().name(),
                         "the ghost promised a different node than the "
                         "drop created")
        self.assertEqual(
            "", dragdrop_widgets.GridGestureMixin._ghost_type(
                self.panel, rule, "code", vop),
            "a network with no carrier still got a promise")

    def test_every_borrowed_overlay_is_given_back(self):
        """The overlay is ONE slot per editor, so a ghost left behind sticks to the artist's network - dragengine.end() clears it on release, cancel and the leave the host treats as a suspend."""
        from amaze.core import dragengine
        given_back = []

        class _Editor:
            def setOverlayShapes(self, shapes):
                if not shapes:
                    given_back.append(True)

        editor = _Editor()
        dragengine._ghosted.append(editor)
        dragengine.end()
        self.assertTrue(given_back, "the overlay was never returned")
        self.assertEqual([], dragengine._ghosted,
                         "the engine still believes it owns an overlay")

    def test_the_editor_is_put_back_in_its_own_network(self):
        """An import tags its nodes current and an unpinned editor follows the selection, so it DIVES - restoring the current node alone does not undo that, so the editor's PWD is remembered and restored too."""
        from unittest import mock
        import types
        from amaze.helpers import helpers
        home = self._geo()
        away = hou.node("/mat")
        anchor = home.createNode("box")
        seen = []

        class _Tab:
            def type(self):
                return hou.paneTabType.NetworkEditor

            def pwd(self):
                return self._pwd

            def setPwd(self, node):
                self._pwd = node
                seen.append(("pwd", node.path()))

            def currentNode(self):
                return anchor

            def setCurrentNode(self, node):
                seen.append(("current", node.path()))

        tab = _Tab()
        tab._pwd = home
        ui = types.SimpleNamespace(paneTabs=lambda: [tab])
        with mock.patch.object(hou, "ui", ui, create=True):
            with helpers.preserving_selection_and_current():
                tab._pwd = away          # the dive an import causes
        self.assertEqual(home, tab.pwd(),
                         "the editor was left in the network the "
                         "import dived into")
        self.assertIn(("pwd", home.path()), seen)

    def test_putting_the_selection_back_costs_no_undo_steps(self):
        """Selection calls push `Change Selection` undo entries (research.md ▸ Viewport & picking), so the whole restore runs under hou.undos.disabler() or every drop sprays undo steps."""
        from unittest import mock
        from amaze.helpers import helpers
        net = self._geo()
        a = net.createNode("box")
        b = net.createNode("sphere")
        hou.clearAllSelected()
        a.setSelected(True)
        real = hou.undos.disabler
        used = []

        def _watch():
            used.append(True)
            return real()

        with mock.patch.object(hou.undos, "disabler", _watch):
            with helpers.preserving_selection_and_current():
                a.setSelected(False)
                b.setSelected(True)
        self.assertTrue(used, "the restore ran outside a disabler - "
                              "every drop now costs undo steps")
        self.assertEqual((a,), hou.selectedNodes())

    def test_a_selected_node_that_cannot_take_it_still_creates(self):
        """The selection is a HINT for the click door, not a veto - a selected node with no snippet parm falls through to creation in the visible network."""
        sop = self._geo()
        sphere = sop.createNode("sphere")
        hou.clearAllSelected()
        sphere.setSelected(True)
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.panel.click_on_row(self.panel.sections["code"], index)
        wrangles = [c for c in sop.children()
                    if "wrangle" in c.type().name()]
        self.assertEqual(
            1, len(wrangles),
            "a selected node that cannot take the snippet blocked the "
            "creation instead of falling through to the network")

    def test_the_MENU_verb_falls_through_exactly_like_the_click(self):
        """Same tile, same selection, one answer: the menu entry sharing the double-click's verb falls through a useless selection the same way - driven through `menu_apply`, the thing the menu table actually names, so a routing regression fails however the body is spelled."""
        sop = self._geo()
        sphere = sop.createNode("sphere")
        hou.clearAllSelected()
        sphere.setSelected(True)
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        section = self.panel.sections["code"]
        section.menu_apply([index], index)
        wrangles = [c for c in sop.children()
                    if "wrangle" in c.type().name()]
        self.assertEqual(
            1, len(wrangles),
            "the menu verb vetoed on a selection the double-click "
            "falls through - same tile, same selection, two answers")

    def test_the_menu_verb_still_fills_a_node_that_CAN_take_it(self):
        """Falling through must not become always-create: a selected node that takes the snippet still takes it, no carrier beside it."""
        sop = self._geo()
        wrangle = sop.createNode("attribwrangle")
        hou.clearAllSelected()
        wrangle.setSelected(True)
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        before = len(sop.children())
        self.panel.sections["code"].menu_apply([index], index)
        self.assertEqual(
            before, len(sop.children()),
            "the menu verb created a carrier beside a node that could "
            "have taken the snippet")

    def test_a_locked_asset_is_skipped_and_the_editable_one_takes_it(self):
        """A SOP Create is a locked HDA whose `create` subnet is the one node marked editable - the walk skips the locked levels (saying why in the log), lands there, and never unlocks the asset."""
        stage = hou.node("/stage")
        sc = stage.createNode("sopcreate")
        self.addCleanup(sc.destroy)
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        section = self.panel.sections["code"]
        editable = sc.node("sopnet/create")
        self.assertTrue(editable.isEditableInsideLockedHDA(),
                        "premise: the create subnet is marked editable")
        self._with_view_networks([sc, sc.node("sopnet"), editable])    # locked levels first - the walk sees all three, only the last can take the carrier
        hou.clearAllSelected()
        before = len(editable.children())
        self.panel.click_on_row(section, index)
        self.assertEqual(before + 1, len(editable.children()),
                         "the walk did not reach the editable subnet")
        self.assertTrue(sc.isLockedHDA(),
                        "the asset was UNLOCKED to make room - never")

    def test_a_geo_double_click_fills_the_selected_node(self):
        """The matrix aims a double-click at the selection first - a selected node with a file parameter takes the spelled path, exactly as the image branch beside it."""
        import types
        from amaze.core import file_library
        from amaze.helpers import helpers
        sop = self._geo()
        loader = sop.createNode("file")
        hou.clearAllSelected()
        loader.setSelected(True)
        self._with_view_networks([sop])
        path = self._home() + "/models/amaze_click.obj"
        roles = {file_library.FileFiles.KindRole: file_library.KIND_GEO,
                 file_library.FileFiles.PathRole: path}
        index = types.SimpleNamespace(
            data=lambda role: roles.get(role, path),
            isValid=lambda: True)
        self.panel.click_on_row(self.panel.sections["file"], index)
        self.assertEqual(
            "$HOME/models/amaze_click.obj",
            helpers.find_file_parm(loader).rawValue(),
            "the selected file node did not take the spelled path")
        self.assertEqual(
            1, len(sop.children()),
            "the door imported beside the selection instead of "
            "filling it")

    def test_an_invisible_selection_cannot_hijack_the_click_door(self):
        """An import leaves its nodes SELECTED, so the next double-click once applied to a selection the user could not see and refused - the door considers only selection inside the visible editors' networks."""
        sop = self._geo()
        elsewhere = self._matnet()
        stray = elsewhere.createNode("mtlxstandard_surface")
        stray.setSelected(True)
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual(
            1, len(sop.children()),
            "an invisible selected node hijacked the click door")

    def test_double_click_with_nothing_selected_creates_the_carrier(self):
        from amaze.helpers import helpers

        home = self._home()
        net = self._matnet()
        self._with_view_networks([net])
        self.panel.click_on_row(
            self.panel.sections["file"],
            self._index_for(home + "/textures/amaze_dbl.png",
                            kind=file_library.KIND_IMAGE))
        children = net.children()
        self.assertEqual(1, len(children),
                         "the empty-selection double-click did not "
                         "create the carrier")
        self.assertEqual(
            "$HOME/textures/amaze_dbl.png",
            helpers.find_file_parm(children[0]).rawValue())

    def test_the_click_doors_find_the_network_that_supports_the_payload(self):
        """ONE resolver walks the visible networks and the first that can hold the carrier wins - the drag and the click once resolved with two different heads and disagreed."""
        vop = self._matnet()
        sop = self._geo()
        self._with_view_networks([vop, sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual((), vop.children(),
                         "the refusing network gained the carrier")
        children = sop.children()
        self.assertEqual(1, len(children),
                         "the supporting network never got the "
                         "carrier - the door gave up on the first "
                         "refusal")
        self.assertIn("attribwrangle", children[0].type().name())

    def test_a_drop_created_node_lands_at_the_release_position(self):
        home = self._home()
        net = self._matnet()
        spot = hou.Vector2(3.5, -2.25)
        self.assertTrue(self.panel.sections["file"].create_image_node_in(
            self._index_for(home + "/textures/amaze_pos.png"), net,
            spot))
        children = net.children()
        self.assertEqual(1, len(children))
        from amaze.helpers import helpers
        anchor = helpers.centred_on(spot)    # the BODY centres on the release point, so the anchor sits a half-size short - helpers.centred_on says why
        self.assertAlmostEqual(anchor.x(), children[0].position().x())
        self.assertAlmostEqual(anchor.y(), children[0].position().y())


class HoudiniPathTest(unittest.TestCase):
    """Copy Path writes paths the way Houdini writes them."""

    def test_a_home_path_collapses_to_the_variable(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        self.assertEqual(
            "$HOME/textures/wood.png",
            file_library.houdini_path(home + "/textures/wood.png"))

    def test_an_unrelated_path_stays_absolute(self):
        self.assertEqual(
            "/mnt/somewhere/else.txt",
            file_library.houdini_path("/mnt/somewhere/else.txt"))

    def test_the_auto_style_is_gone(self):
        """Fails if the removed Auto path style or its machinery returns - and a machine that STORED "auto" lands on the default instead of a dead token."""
        from amaze.dialogs import prefs_dialog
        self.assertNotIn("auto", file_library.PATH_STYLES,
                         "the removed auto path style returned")
        p = test_support.fixture_prefs(self)
        p.path_style = "auto"
        self.assertEqual("home", p.path_style,
                         "a stored 'auto' did not fall back to home")
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combo = dlg._combo_path_style
        self.assertEqual(-1, combo.findData("auto"),
                         "the Write Paths As dropdown offers Auto again")
        self.assertEqual(4, combo.count(),
                         "Write Paths As should offer exactly "
                         "$HOME / $JOB / $HIP / Absolute")

    def test_the_test_library_switch_freezes_the_real_path_rows(self):
        """While the Test Library switch is on, the Library Path row is INERT - its browse button would otherwise write the real field with a test path, the one combination that could lose a library; the Cache Path row stays live, because the cache does not move with the library."""
        import os
        import shutil
        import tempfile
        from amaze.dialogs import prefs_dialog
        from amaze.prefs import prefs as prefs_mod

        p = test_support.fixture_prefs(self)
        real_library = p.dir
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)

        self.assertEqual("Test Library", dlg._cbx_test_mode.text())
        self.assertTrue(dlg.line_workdir.isEnabled(),
                        "the Library Path row starts frozen")
        self.assertEqual(real_library, dlg.line_workdir.text())

        folder = tempfile.mkdtemp(prefix="amaze_switch_")
        self.addCleanup(shutil.rmtree, folder, True)
        prefs_mod.seed_test_folder(folder)
        p.test_dir = folder
        p.test_mode = True
        dlg._sync_test_mode_rows()

        self.assertEqual(
            test_support.posix_path(os.path.join(folder, "lib") + "/"),    # p.dir answers forward-slashed, so the expectation is spelled that way - bare os.path.join reddens on Windows
            p.dir)
        self.assertEqual(p.dir, dlg.line_workdir.text(),
                         "the row still shows the real library while "
                         "the panel reads the test one")
        self.assertFalse(dlg.line_workdir.isEnabled(),
                         "the Library Path row is live while Test "
                         "Library is on - its browse writes the real "
                         "field")
        self.assertTrue(dlg.line_cache.isEnabled(),
                        "the Cache Path row was frozen - the cache "
                        "does not move with the library")

        p.test_mode = False
        dlg._sync_test_mode_rows()
        self.assertEqual(real_library, p.dir,
                         "the real library did not come back")
        self.assertTrue(dlg.line_workdir.isEnabled())

    def test_default_puts_the_cache_path_back(self):
        """The Cache Path row's Default button CLEARS the preference rather than writing today's default as a literal path, so the cache keeps following this machine's own convention."""
        from amaze.dialogs import prefs_dialog
        from amaze.helpers import hostos as hostos_mod

        p = test_support.fixture_prefs(self)
        p.cache_dir = "/somewhere/else"
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual("Default", dlg._default_cache.text())

        dlg.reset_cache_path()

        self.assertEqual("", p.cache_dir,
                         "a literal path was written instead of the "
                         "preference being cleared")
        self.assertEqual(hostos_mod.cache_root(), dlg.line_cache.text(),
                         "the field still shows the old path")

    def test_the_user_field_shows_a_real_name(self):
        """The User row shows WHO this is - the one identity keying the per-user things and signing versions - and a fresh prefs mints the first user RIGHT THERE and shows the name, never a promise for later."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        p.library_user = ""    # NOBODY, said out loud - the mint only happens on an empty pointer
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        shown = dlg.cbb_library_user.currentText()
        self.assertIn(shown, users.PLACEHOLDER_NAMES,
                      "a library with nobody in it must mint its first "
                      "user right here and show the NAME")
        uid = p.library_user
        self.assertNotEqual(shown, uid,
                            "the box is showing the UID - a person no "
                            "more reads that than an IP address")
        dlg.rename_library_user("  MyOwnName  ")
        self.assertEqual("MyOwnName", users.name_for(p, uid),
                         "typed name (trimmed) did not relink the UID")
        self.assertEqual(uid, p.library_user,
                         "a RENAME minted a new identity - everything "
                         "already tagged would be orphaned")

    def test_the_user_row_switches_between_the_librarys_users(self):
        """The User row is a dropdown over the LIBRARY's users, so a person on another machine picks themselves instead of becoming a stranger."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        first = users.create(p, "Cobalt")
        second = users.create(p, "Sienna")
        p.library_user = first
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combo = dlg.cbb_library_user
        listed = {combo.itemText(i) for i in range(combo.count())}
        self.assertIn("Cobalt", listed)
        self.assertIn("Sienna", listed)
        self.assertEqual("Cobalt", combo.currentText(),
                         "the box opened on somebody else")
        combo.setCurrentIndex(combo.findData(second))
        self.assertEqual(second, p.library_user,
                         "picking a user did not switch this machine")

    def test_the_edit_button_renames_without_minting(self):
        """A rename relinks the label on the SAME UID - everything already tagged stays tagged."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        uid = users.create(p, "Cobalt")
        p.library_user = uid
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        dlg.rename_library_user("  Sienna  ")
        self.assertEqual("Sienna", users.name_for(p, uid))
        self.assertEqual(uid, p.library_user,
                         "the rename minted a new identity")
        self.assertEqual("Sienna", dlg.cbb_library_user.currentText(),
                         "the dropdown still shows the old name")
        self.assertEqual(1, len(users.all_users(p)))

    def test_the_default_style_pins_home(self):
        """Write Paths As defaults to $HOME: a path under $HIP still says $HOME/... unless the user chooses otherwise."""
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        hip = hou.expandString("$HIP").replace("\\", "/").rstrip("/")
        if not hip or not hip.startswith(home + "/"):
            self.skipTest("$HIP does not live under $HOME here")
        collapsed = file_library.houdini_path(hip + "/render.exr")
        self.assertTrue(collapsed.startswith("$HOME/"),
                        "the default style is not $HOME: %r" % collapsed)

    def test_absolute_style_never_collapses(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        self.assertEqual(
            home + "/x.png",
            file_library.houdini_path(home + "/x.png", "absolute"))

    def test_the_pref_validates_and_defaults_home(self):
        from amaze.prefs import prefs as prefs_module
        p = prefs_module.Prefs()
        self.assertEqual("home", p.path_style)
        p.path_style = "job"
        self.assertEqual("job", p.path_style)
        p.path_style = "nonsense"
        self.assertEqual("home", p.path_style,
                         "an invalid token was accepted")


class _Prefs:
    """Only what FileFiles reads, OVER THE REAL LOCATION STORE - `file_folders` and the decoration tables are derived, not held, and a stub carrying them as plain attributes would accept every write, answer none, and let the tests pass their own values back to themselves while the code read an empty store."""

    def __init__(self, folders=()):
        self.dir = tempfile.mkdtemp(prefix="amaze_file_lib_")
        self.library_user = test_support.FIXTURE_USER    # a user-tagged store with no user describes the ASK window, not a working machine - every register would refuse
        self.file_show_unknown = True
        self.path_style = "home"
        self.last_file_folder = ""
        self.rendersize = 256
        self.icon_line_weight = "template"
        self.texture_parallel_conversions = 1
        self.geometry_shading_mode = "hiddenlineghost"
        self.geometry_bg = "black"
        self._records: dict = {}
        self._order: list = []
        self._favourites: list = []
        for path in folders:
            self.add_file_folder(path)

    @property
    def last_known_folders(self):
        return self._order

    @property
    def last_known_favourites(self):
        return self._favourites

    @property
    def last_known_records(self):
        return self._records

    def keep_last_known(self, records, order, favourites):
        if records is not None:
            self._records = {k: dict(v) for k, v in records.items()}
        if order is not None:
            self._order = list(order)
        if favourites is not None:
            self._favourites = list(favourites)

    def save(self):
        pass

    @property
    def file_folders(self):
        return locations_mod.registered_paths(self)

    @property
    def file_favorites(self):
        return locations_mod.favourite_paths(self)

    @property
    def file_recursive_folders(self):
        return [p for p in locations_mod.registered_paths(self)
                if locations_mod.record(self, p).get("recursive")]

    @property
    def file_folder_names(self):
        return self._table("name")

    @property
    def file_folder_colors(self):
        return self._table("color")

    @property
    def file_folder_show_all(self):
        return self._table("show_all")

    def _table(self, field):
        table = {}
        for path in locations_mod.paths(self):
            record = locations_mod.record(self, path)
            if field in record:
                table[path] = record[field]
        return table

    def add_file_folder(self, path):
        locations_mod.register(self, path)

    def remove_file_folder(self, path):
        locations_mod.unregister(self, path)

    def relocate_file_folder(self, old, new):
        record = locations_mod.record(self, old)
        if not record:
            return False
        at = self._order.index(old) if old in self._order else len(self._order)
        locations_mod.relocate_record(self, old, new)    # the PRODUCT door (prefs.relocate_file_folder) - the forget-and-recreate pair this replaced minted a fresh identity and orphaned every star under the old one
        if new in self._order:
            self._order.remove(new)
        self._order.insert(min(at, len(self._order)), new)
        return True

    def add_file_favorite(self, path):
        locations_mod.set_favourite(self, path, True)

    def remove_file_favorite(self, path):
        locations_mod.set_favourite(self, path, False)

    def set_file_folder_name(self, path, name):
        locations_mod.set_field(self, path, "name", str(name or "").strip())

    def set_file_folder_color(self, path, color):
        locations_mod.set_field(self, path, "color", str(color or "").strip())

    def set_file_folder_show_all(self, path, value):
        locations_mod.set_field(self, path, "show_all",
                                None if value is None else bool(value))

    def set_file_folder_recursive(self, path, on):
        locations_mod.set_field(self, path, "recursive", bool(on) or None)


class FileKeyIsCanonicalTest(unittest.TestCase):
    """file_key is the identity everything keyed about a file hangs on (comment, icon override, drag bookkeeping), so the same file produces the SAME key however its location was spelled - the detour registration is not exotic: `hou.text.expandString` substitutes verbatim, so real `$AMAZE`-relative locations carry `../../..` in every key."""

    def _model_over(self, folder):
        from amaze.helpers import hostos  # noqa: F401 - guard below
        model = file_library.FileFiles(_Prefs([folder]))
        model.set_folder(folder)
        return model

    def test_the_key_is_one_spelling_however_the_location_is_spelled(self):
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.mkdir(os.path.join(tmp, "sub"))
        with open(os.path.join(tmp, "a.png"), "w") as handle:
            handle.write("x")
        detour = os.path.join(tmp, "sub", os.pardir)
        model = self._model_over(detour)
        self.assertGreater(model.rowCount(), 0, "the fixture scanned "
                                                "nothing - this test is "
                                                "not testing keys")
        straight = file_library.FileFiles(model.preferences)
        straight.set_folder(tmp)
        keys = [model.file_key(r) for r in range(model.rowCount())]
        self.assertEqual(
            keys,
            [straight.file_key(r) for r in range(straight.rowCount())],
            "the same file reached through a differently-spelled "
            "location gets a different identity, and its comment and "
            "icon are keyed to the spelling")
        for key in keys:
            self.assertTrue(
                key.startswith("loc:"),
                "file_key %r is not the location-keyed ident - keyed "
                "by path, a moved folder orphans it" % key)

    def test_an_out_of_range_row_stays_empty(self):
        """normpath("") is ".", so a blind canonicalise would turn the no-such-row answer into a truthy path every `if not key` guard misses."""
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        model = self._model_over(tmp)
        self.assertEqual("", model.file_key(999))
        self.assertEqual("", model.file_key(-1))


class OsIconTest(unittest.TestCase):
    """A file Amaze does not recognise still gets a picture: the OS's own icon on a transparent tile-sized canvas, never scaled past 2x its native size (the recorded probe's caveat)."""

    def _model_with(self, *names):
        tmp = tempfile.mkdtemp(prefix="amaze_osicon_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in names:
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        model = file_library.FileFiles(_Prefs([tmp]))
        model.set_folder(tmp)
        return model

    def test_an_unknown_extension_is_never_blank(self):
        model = self._model_with("mocap.bvh")
        image = model.data(model.index(0, 0),
                           QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertIsNotNone(image, "an unrecognised file has no tile "
                             "picture at all")
        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), image.height())
        opaque = any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(0, image.width(), 16)
            for y in range(0, image.height(), 16))
        self.assertTrue(opaque, "the OS icon canvas is fully "
                        "transparent - nothing was drawn on it")

    def test_a_file_with_no_extension_gets_the_generic_icon(self):
        model = self._model_with("README")
        image = model.data(model.index(0, 0),
                           QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertIsNotNone(image)
        self.assertFalse(image.isNull())

    def test_one_icon_is_composed_per_extension_not_per_file(self):
        model = self._model_with("a.log", "b.log", "c.log")
        for row in range(3):
            model.data(model.index(row, 0),
                       QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual(1, len(model._os_icons),
                         "a folder of logs composed three identical "
                         "icons instead of one")


class _RecordingPanel:
    """A stand-in `self` for the live click door - click_on_row and _apply_click_rule run for real, and the panel PLUMBING each section verb reaches for records instead of touching a scene."""

    file_files_model = file_library.FileFiles

    def __init__(self):
        self.calls = []
        self.prefs = _Prefs([])

    def _visible_selected_nodes(self):
        """Nothing selected - the dispatch test drives the per-kind routing, not the selection door."""
        return []

    def _view_create_networks(self):
        """One writable network, so the on-space route can land."""
        return [object()]

    def _cannot_load_here(self):
        self.calls.append("refused")

    def import_geo_asset(self, index):
        self.calls.append("import_geo_asset")

    def copy_file_paths(self, indexes):
        self.calls.append("copy_file_paths")


class _FakeIndex:
    def __init__(self, kind, path="/x/y.ext"):
        self._kind = kind
        self._path = path

    def isValid(self):
        return True

    def data(self, role):
        if role == file_library.FileFiles.KindRole:
            return self._kind
        if role == file_library.FileFiles.PathRole:
            return self._path
        return None


class DoubleClickDispatchTest(unittest.TestCase):
    """Each kind reaches its own verb THROUGH THE LIVE DOOR over a real FileSection with nothing selected - breaks when a DROP_BY_KIND row loses its verb, names a different one, or the door's precedence stops reaching the no-node route."""

    def test_every_kind_reaches_its_own_verb(self):
        from amaze.panel import panel as panel_mod
        from amaze.panel import sections
        for kind, expected in (("image", "create_image_node_in"),
                               ("geometry", "import_geo_asset"),
                               ("hip", "open_hip_scene"),
                               ("other", "copy_file_paths"),
                               ("", "copy_file_paths")):
            recorder = _RecordingPanel()
            recorder._apply_click_rule = (
                panel_mod.MatLibPanel._apply_click_rule.__get__(recorder))
            section = sections.FileSection(recorder)
            section.create_image_node_in = (
                lambda index, network, position=None:
                recorder.calls.append("create_image_node_in") or True)
            section.open_hip_scene = (
                lambda index: recorder.calls.append("open_hip_scene"))
            panel_mod.MatLibPanel.click_on_row(
                recorder, section, _FakeIndex(kind))
            self.assertEqual([expected], recorder.calls,
                             "kind %r dispatched %r" % (kind,
                                                        recorder.calls))


class CopyPathTest(unittest.TestCase):
    """Copy Path fills the clipboard with HOUDINI paths, one per line, and no dialog."""

    def test_paths_land_houdini_shaped_one_per_line(self):
        from amaze.panel import panel as panel_mod
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        recorder = _RecordingPanel()
        recorder._scene_path = (    # the real spelling home, bound to the stub
            lambda p: panel_mod.MatLibPanel._scene_path(recorder, p))
        panel_mod.MatLibPanel.copy_file_paths(recorder, [
            _FakeIndex("other", home + "/mocap/walk.bvh"),
            _FakeIndex("image", "/mnt/elsewhere/tex.png"),
        ])
        text = QtWidgets.QApplication.clipboard().text()
        self.assertEqual(
            "$HOME/mocap/walk.bvh\n/mnt/elsewhere/tex.png", text,
            "the clipboard does not carry Houdini-shaped paths, one "
            "per line")


class HipDragLoadsOutsideTest(unittest.TestCase):
    """A hip dragged OUTSIDE Amaze loads the scene like double-click; released inside the panel it stays silent, because a drag that ends where it began is not a decision."""

    def _armed_hip(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_drag_gesture as harness_mod
        h = harness_mod._Harness(self, "file", kind="hip")
        h.section.open_hip_scene = (
            lambda idx: h.panel.calls.append("open"))
        h.press()
        h.view._dragging = True
        h.view._drag_panel = h.panel
        return h

    def _release_at_global(self, h, global_point):
        """The inside/outside decision reads event.globalPosition(), and a locally-constructed QMouseEvent defaults that to the REAL cursor - so the test says the global point explicitly."""
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(10, 10),
            QtCore.QPointF(global_point),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        h.view.mouseReleaseEvent(event)

    def test_released_outside_the_panel_loads_the_scene(self):
        h = self._armed_hip()
        self._release_at_global(h, QtCore.QPoint(5000, 5000))
        self.assertIn("open", h.panel.calls,
                      "a hip dragged out of Amaze did not load")

    def test_released_inside_the_panel_stays_silent(self):
        h = self._armed_hip()
        inside = h.panel.mapToGlobal(QtCore.QPoint(5, 5))
        self._release_at_global(h, inside)
        self.assertNotIn("open", h.panel.calls,
                         "a drag that never left the panel loaded the "
                         "scene anyway")


class TooltipWidthTest(unittest.TestCase):
    """Tooltips cap at 800 REAL screen pixels and wrap - a plain-text tooltip renders as one line however long, and a logical-px cap doubles on a Retina screen."""

    def _with_dpr(self, dpr):
        """Pin the screen ratio the cap divides by, restored after."""
        from amaze.helpers import theme
        original = theme.screen_ratio
        theme.screen_ratio = lambda widget=None: dpr
        self.addCleanup(setattr, theme, "screen_ratio", original)

    def test_a_short_tooltip_passes_through_untouched(self):
        from amaze.helpers import ui_helpers
        self.assertEqual("Short and sweet",
                         ui_helpers.tooltip_text("Short and sweet"))

    def test_markup_in_a_SHORT_tooltip_draws_as_text_not_as_html(self):
        """A catalogue entry's title is remote text, and Qt auto-detects rich text - so a short one used to reach the tooltip as live markup. ▸r/tooltip-autodetect"""
        from PySide6 import QtGui
        from amaze.helpers import ui_helpers
        hostile = '<img src="http://evil.invalid/beacon.png">'
        out = ui_helpers.tooltip_text(hostile)

        document = QtGui.QTextDocument()
        document.setHtml(out)
        self.assertEqual(
            hostile, document.toPlainText(),
            "the tooltip renders the catalogue's markup instead of "
            "showing it, so an <img> reaches a URL the catalogue chose")

    def test_arithmetic_in_a_tooltip_is_left_alone(self):
        """Escaping everything would turn `5 < 6` into `5 &lt; 6` on screen; Qt reads it as plain, so it must pass through."""
        from amaze.helpers import ui_helpers
        self.assertEqual("5 < 6 and 7 > 2",
                         ui_helpers.tooltip_text("5 < 6 and 7 > 2"))

    def test_a_catalogue_record_s_tooltip_is_escaped(self):
        """The real sink: title, author and licence all come off the wire. ▸r/tooltip-autodetect"""
        from PySide6 import QtGui
        from amaze.helpers import ui_helpers
        record = "\n".join(["<b>Free</b> Brick", "by <i>nobody</i>", "CC0"])
        document = QtGui.QTextDocument()
        document.setHtml(ui_helpers.tooltip_text(record))
        self.assertIn("<b>Free</b> Brick", document.toPlainText())

    def test_a_long_tooltip_becomes_a_width_capped_table(self):
        from amaze.helpers import ui_helpers
        self._with_dpr(1.0)
        long = ("This explanation goes on and on, well past any "
                "reasonable single line of screen, because it has a "
                "lot of genuinely useful things to say about what the "
                "switch does and when a person would want it off.") * 2
        wrapped = ui_helpers.tooltip_text(long)
        self.assertIn('width="800"', wrapped,
                      "the long tooltip is not capped at 800px")
        self.assertTrue(wrapped.startswith("<qt>"),
                        "not rich text - Qt will not wrap it")

    def test_the_cap_is_real_pixels_not_logical(self):
        """On a 2x screen a ~720-logical-px sentence slips a logical cap of 800 and draws ~1450 real pixels wide - in real pixels the cap is 400 logical there, and it wraps."""
        from amaze.helpers import ui_helpers
        self._with_dpr(2.0)
        reported = ("Show files Amaze cannot thumbnail in the File "
                    "section, with their system icon. Off = the File "
                    "section shows only images, geometry and scene "
                    "files.")
        wrapped = ui_helpers.tooltip_text(reported)
        self.assertTrue(wrapped.startswith("<qt>"),
                        "the reported tooltip still draws as one "
                        "plain unwrapped line on a 2x screen")
        self.assertIn('width="400"', wrapped,
                      "the cap did not divide out the 2x ratio - "
                      "800 logical is 1600 real pixels on that screen")


class StarRowsLeftPreferencesTest(unittest.TestCase):
    """The badge family renders the favourite star AS DRAWN, so the star-colour rows left the dialog, the keys left the store, and the notes accent pinned to the theme's star token."""

    def test_the_two_rows_are_gone_and_a_neighbour_remains(self):
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        labels = [lab.text() for lab in dlg.findChildren(QtWidgets.QLabel)]
        for gone in ("Favorite Star", "Custom Star Color"):
            self.assertNotIn(
                gone, labels,
                "the '%s' row is back in Preferences - it was removed "
                "with the unified badge family" % gone)
        self.assertIn(
            "Tile Icon Line", labels,
            "the neighbouring row is missing too - this scan is not "
            "looking at the built dialog")

    def test_the_preferences_object_dropped_the_properties(self):
        p = test_support.fixture_prefs(self)
        for gone in ("star_color_mode", "star_custom_color"):
            self.assertFalse(
                hasattr(p, gone),
                "prefs.%s exists again - the star-colour preference "
                "was removed outright, not orphaned" % gone)

    def test_stale_star_keys_drop_and_future_keys_survive_a_save(self):
        """save()'s unknown-key courtesy rightly KEEPS a newer build's keys but would re-adopt retired ones from disk on every write - the hole _RETIRED_KEYS closes; both behaviours proven on one file."""
        import json
        p = test_support.fixture_prefs(self)
        p.save()
        final = p.path + "/settings.json"
        with open(final, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["star_color_mode"] = "custom"
        raw["star_custom_color"] = "#123456"
        raw["texture_folders"] = ["/tex/a/"]    # the merged sections' retired quartets - a real pre-sweep settings.json carries these
        raw["geometry_favorites"] = ["/geo/c/rock.bgeo"]
        raw["hip_include_subfolders"] = True
        raw["file_section_migrated"] = True
        raw["key_from_a_newer_build"] = "kept"
        with open(final, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=4)
        p.save()
        with open(final, encoding="utf-8") as handle:
            after = json.load(handle)
        for gone in ("star_color_mode", "star_custom_color",
                     "texture_folders", "geometry_favorites",
                     "hip_include_subfolders", "file_section_migrated"):
            self.assertNotIn(
                gone, after,
                "a retired key rode the unknown-key courtesy back "
                "into settings.json - it will now live there forever")
        self.assertEqual(
            "kept", after.get("key_from_a_newer_build"),
            "the courtesy for a NEWER build's keys broke - retirement "
            "must name its keys, not drop everything unknown")


class PrefsComboFocusTest(unittest.TestCase):
    """Every Preferences dropdown refuses focus - Houdini's stylesheet paints a focused combo navy with a blue ring, permanently singling out whichever was last clicked; the dialog's NoFocus sweep once ran before the tab widget joined the tree and fixed nothing."""

    def test_every_prefs_combo_refuses_focus(self):
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combos = dlg.findChildren(QtWidgets.QComboBox)
        self.assertGreater(
            len(combos), 3,
            "the dialog built no dropdowns to check - this test can "
            "no longer prove the sweep runs")
        wrong = ["%s (policy %s)" % (c.currentText() or "unnamed",
                                     c.focusPolicy())
                 for c in combos
                 if c.focusPolicy() != QtCore.Qt.FocusPolicy.NoFocus]
        self.assertEqual(
            [], wrong,
            "dropdowns still take focus, so Houdini's navy focus ring "
            "singles out the last-clicked one: %s" % wrong)

    def test_paragraph_breaks_survive_the_wrap(self):
        from amaze.helpers import ui_helpers
        text = ("First paragraph, made long enough to trip the cap "
                "by repeating itself. " * 5) + "\n\nSecond paragraph."
        self.assertIn("<br><br>Second paragraph.",
                      ui_helpers.tooltip_text(text),
                      "rich text ate the paragraph break")

    def test_every_dialog_tooltip_goes_through_the_cap(self):
        """Source-derived: a bare multi-line setToolTip is the exact shape that regresses into the screen-wide bar."""
        import re
        package = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("dialogs/prefs_dialog.py", "panel/panel.py"):
            with open(os.path.join(package, name),
                      encoding="utf-8") as handle:
                body = handle.read()
            for match in re.finditer(r"\.setToolTip\(\s*\n", body):
                line = body.count("\n", 0, match.start()) + 1
                if "tooltip_text" not in body[
                        match.start():match.end() + 40]:
                    offenders.append("%s:%d" % (name, line))
        self.assertEqual([], offenders,
                         "multi-line tooltips bypass the width cap: "
                         "%s" % offenders)

    def test_no_tooltip_speaks_developer(self):
        """Nobody out there knows what 'the merge' was."""
        import re
        package = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(package, "dialogs/prefs_dialog.py"),
                  encoding="utf-8") as handle:
            body = handle.read()
        for match in re.finditer(
                r"setToolTip\(.*?\)\)", body, re.S):
            self.assertNotIn(
                "the merge", match.group(),
                "a tooltip references 'the merge' - project history "
                "no user has")


class LocationManagementTest(unittest.TestCase):
    """The four confirmed location asks: removal sweeps the folder's cached thumbnails, recursion is per location, the default name is the Houdini-collapsed path itself, and a location can be renamed - with Locate carrying both along."""

    def _folders_model(self, *paths):
        prefs = _Prefs(list(paths))
        return file_library.FileFolders(prefs), prefs

    def _tmpdir(self, prefix="amaze_loc_"):
        tmp = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp

    def test_recursion_is_per_location(self):
        deep = self._tmpdir()
        flat = self._tmpdir()
        for base in (deep, flat):
            sub = os.path.join(base, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "buried.txt"), "w") as handle:
                handle.write("x")
            with open(os.path.join(base, "top.txt"), "w") as handle:
                handle.write("x")
        prefs = _Prefs([deep, flat])
        prefs.set_file_folder_recursive(deep, True)
        model = file_library.FileFiles(prefs)
        model.set_folder(deep)
        self.assertEqual(2, model.rowCount(),
                         "the recursive location did not descend")
        model.set_folder(flat)
        self.assertEqual(1, model.rowCount(),
                         "the flat location descended anyway - "
                         "recursion leaked across locations")
        folders_model = file_library.FileFolders(prefs)
        from amaze.core import category
        counts = [folders_model.data(folders_model.index(i, 0),
                                     category.SIDEBAR_COUNT_ROLE)
                  for i in (1, 2)]
        self.assertEqual([2, 1], counts,
                         "the counts do not follow each location's own "
                         "recursion flag")

    def test_the_default_name_is_the_folder_s_own_name(self):
        """The row says what the folder IS; the full path is the hover, not the label. Said the collapsed path until 2026-08-27."""
        model, _prefs = self._folders_model("/assets/textures/HDR/")
        label = model.data(model.index(1, 0),
                           QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual("HDR", label,
                         "the default label is not the folder's name: %r"
                         % label)

    def test_a_rename_wins_and_an_empty_rename_clears(self):
        model, prefs = self._folders_model("/assets/textures/")
        prefs.set_file_folder_name("/assets/textures/", "Set Dressing")
        self.assertEqual("Set Dressing", model.data(
            model.index(1, 0), QtCore.Qt.ItemDataRole.DisplayRole))
        prefs.set_file_folder_name("/assets/textures/", "")
        label = model.data(model.index(1, 0),
                           QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertIn("textures", label,
                      "clearing the name did not fall back to the path")

    def test_locate_carries_name_and_recursion(self):
        old = self._tmpdir()
        new = self._tmpdir()
        model, prefs = self._folders_model(old)
        prefs.set_file_folder_name(old, "Set Dressing")
        prefs.set_file_folder_recursive(old, True)
        prefs.save = lambda: None
        rewritten = model.relocate_folder(1, new)
        self.assertGreaterEqual(rewritten, 0, "relocate refused")
        new_key = hostos.canonical_path_key(new) + "/"    # canonical - the locations API's spelling
        self.assertEqual({new_key: "Set Dressing"},
                         prefs.file_folder_names,
                         "the custom name did not follow the move")
        self.assertEqual([new_key], prefs.file_recursive_folders,
                         "the recursion flag did not follow the move")

    def test_locate_moves_the_pointer_and_the_favourites(self):
        """Locate's two writes nothing else asserts: the registered pointer moves IN ITS OWN ROW (no sidebar reorder) and every favourite under the old path is rewritten onto the new one - both fail as silent no-ops, so only the END STATE can see them."""
        first = self._tmpdir()
        old = self._tmpdir()
        new = self._tmpdir()
        old_key = old if old.endswith("/") else old + "/"
        prefs = _prefs_with_settings(self, {    # a REAL Prefs, not the stub: a stub carrying its own copy of the move would only verify the copy
            "file_folders": [first, old],
            "file_favorites": [old_key + "keep.exr", "/elsewhere/other.exr"],
            "file_location_records": {
                first: {"registered": True},
                old: {"registered": True},
            },
        })
        prefs.dir = self._tmpdir(prefix="amaze_loc_lib_")
        model = file_library.FileFolders(prefs)

        rewritten = model.relocate_folder(2, new)

        new_key = hostos.canonical_path_key(new) + "/"    # canonical on both sides - the API's spelling
        first = hostos.canonical_path_key(first)
        self.assertEqual(1, rewritten,
                         "Locate did not report the favourite it moved")
        self.assertEqual([first, new_key], list(prefs.file_folders),
                         "the registered pointer did not move, or the row "
                         "changed position")
        self.assertEqual(sorted(["/elsewhere/other.exr",    # sorted: the favourites are a keyed store, order is the file's, and nothing reads this list except as membership
                                 new_key + "keep.exr"]),
                         sorted(prefs.file_favorites),
                         "a favourite under the moved location was left "
                         "pointing at the old path")

    def test_removal_sweeps_the_cache_but_not_captures(self):
        """End to end against a real cache layout: the removed folder's thumbnails go, a file another location still covers stays, an unreadable manifest is left alone, and the hip capture store is never touched."""
        import hashlib
        from amaze.helpers import hostos as hostos_mod

        doomed_dir = self._tmpdir()
        kept_dir = self._tmpdir()
        cache_root = hostos_mod.cache_root()
        cache_dir = os.path.join(cache_root, "texture_thumbnails_256")
        os.makedirs(cache_dir, exist_ok=True)

        def entry(folder, name):
            path = hostos_mod.canonical_path_key(
                os.path.join(folder, name))
            png = os.path.join(
                cache_dir,
                hashlib.sha1(path.encode()).hexdigest() + ".png")
            with open(png, "wb") as handle:
                handle.write(b"png")
            return path, png

        doomed_path, doomed_png = entry(doomed_dir, "a.png")
        kept_path, kept_png = entry(kept_dir, "b.png")
        manifest = {doomed_path: {"mtime": 1, "size": 3},
                    kept_path: {"mtime": 1, "size": 3}}
        with open(os.path.join(cache_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        self.addCleanup(shutil.rmtree, cache_dir, ignore_errors=True)

        bad_dir = os.path.join(cache_root, "geo_thumbnails_bad_black_256")    # an unreadable sibling manifest must be left alone entirely
        os.makedirs(bad_dir, exist_ok=True)
        with open(os.path.join(bad_dir, "manifest.json"), "w") as f:
            f.write("{corrupt")
        self.addCleanup(shutil.rmtree, bad_dir, ignore_errors=True)

        from amaze.core import scene_captures    # a capture store with content that must survive
        capture_dir = scene_captures.thumb_dir()
        marker = os.path.join(capture_dir, "sweep_canary.png")
        with open(marker, "wb") as handle:
            handle.write(b"capture")
        self.addCleanup(lambda: os.path.exists(marker)
                        and os.remove(marker))

        removed = file_library.sweep_folder_cache(
            _Prefs([]), doomed_dir, [kept_dir])
        self.assertEqual(1, removed)
        self.assertFalse(os.path.exists(doomed_png),
                         "the removed folder's thumbnail survived")
        self.assertTrue(os.path.exists(kept_png),
                        "another location's thumbnail was swept")
        with open(os.path.join(cache_dir, "manifest.json")) as f:
            left = json.load(f)
        self.assertEqual([kept_path], list(left),
                         "the manifest does not match the sweep")
        with open(os.path.join(bad_dir, "manifest.json")) as f:
            self.assertEqual("{corrupt", f.read(),
                             "an unreadable manifest was rewritten")
        self.assertTrue(os.path.exists(marker),
                        "the sweep touched the capture store")

    def test_remove_folder_drops_the_per_location_state(self):
        """ALL FOUR per-location surfaces read AFTERWARDS - a spy on which setters ran could not see the mechanism running two short, which it did."""
        tmp = self._tmpdir()
        kept = self._tmpdir()    # TWO locations, assertions read the SURVIVOR: with one, retired-record and wiped-everything are the same observation
        model, prefs = self._folders_model(tmp, kept)
        for path, name, colour, show, in ((tmp, "Custom", "#ff8000", True),
                                          (kept, "Kept", "#0080ff", False)):
            prefs.set_file_folder_name(path, name)
            prefs.set_file_folder_color(path, colour)
            prefs.set_file_folder_show_all(path, show)
            prefs.set_file_folder_recursive(path, True)
        prefs.save = lambda: None
        prefs.remove_file_folder = (    # remove_folder mutates prefs.file_folders via the real Prefs method; the stub needs it
            lambda path: prefs.file_folders.remove(path))
        from unittest import mock
        with mock.patch.object(
                file_library, "sweep_folder_cache") as sweep:
            model.remove_folder(1)
        kept = hostos.canonical_path_key(kept)    # canonical - mkdtemp made these natively
        tmp = hostos.canonical_path_key(tmp)
        self.assertEqual({kept: "Kept"}, prefs.file_folder_names,
                         "the custom name outlived its folder, or the "
                         "removal reached the location NEXT to it")
        self.assertEqual([kept], prefs.file_recursive_folders,
                         "the recursion flag outlived its folder, or "
                         "the removal reached its neighbour")
        self.assertEqual(
            {kept: "#0080ff"}, prefs.file_folder_colors,
            "the location's COLOUR outlived its folder, so re-adding "
            "the same path comes back amber with nothing having said "
            "the colour was kept - or the removal took the neighbour's "
            "colour with it")
        self.assertEqual(
            {kept: False}, prefs.file_folder_show_all,
            "the Show All Files override outlived its folder, or the "
            "removal reached its neighbour")
        sweep.assert_called_once_with(prefs, tmp, [kept])


class CleanupPrunesThroughTheModelTest(unittest.TestCase):
    """Clean Library drops dead location pointers through the MODEL - the rows come straight out of prefs, so a bare prefs write changes the count with no structural signal (research.md ▸ A BARE layoutChanged.emit() SEGFAULTS H21 TOO); three locations with the live one BETWEEN the dead two, the setup a low-row-first removal fails on."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_dead_locations_go_through_beginRemoveRows(self):
        panel = self.panel
        model = panel.file_folders_model
        dead_a, alive, dead_b = [
            tempfile.mkdtemp(prefix="amaze_cleanup_%s_" % name)
            for name in ("dead_a", "alive", "dead_b")
        ]
        for path in (dead_a, alive, dead_b):
            self.addCleanup(shutil.rmtree, path, ignore_errors=True)
            self.addCleanup(panel.prefs.remove_file_folder, path)
            model.add_folder(path)
        for path in (dead_a, dead_b):
            shutil.rmtree(path)

        removed = []
        model.rowsRemoved.connect(
            lambda _parent, first, last: removed.append((first, last)))
        before = model.rowCount()
        panel._cleanup_browser_prefs()

        self.assertEqual(
            2, len(removed),
            "cleanup dropped %d location(s) with %d rowsRemoved - the "
            "model's rows come straight from prefs, so a write there "
            "with no structural signal leaves every attached view on a "
            "stale row count"
            % (before - model.rowCount(), len(removed)))
        survivors = list(panel.prefs.file_folders)
        self.assertIn(    # the locations API answers CANONICAL absolutes, so the expectation converts too
            hostos.canonical_path_key(alive), survivors,
            "cleanup removed a location whose folder is still there")
        for path in (dead_a, dead_b):
            self.assertNotIn(
                hostos.canonical_path_key(path), survivors,
                "a dead location survived cleanup - the second removal "
                "aimed at a row the first one had already shifted")


class ShowUnknownFilesSwitchTest(unittest.TestCase):
    """Show Unknown Files ON (the default) means a folder shows what is in it; OFF restores the recognised-kinds-only view, and the sidebar count agrees with the grid in BOTH states."""

    def _folder(self):
        tmp = tempfile.mkdtemp(prefix="amaze_unknown_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("a.png", "b.obj", "c.hip", "d.bvh", "e.txt"):
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        return tmp

    def test_the_default_shows_everything(self):
        from amaze.prefs import prefs as prefs_module
        self.assertTrue(prefs_module.Prefs().file_show_unknown,
                        "the default hides files - the merge's whole "
                        "point was a folder showing what is in it")

    def test_off_restores_the_pre_merge_view(self):
        tmp = self._folder()
        prefs = _Prefs([tmp])
        prefs.file_show_unknown = False
        model = file_library.FileFiles(prefs)
        model.set_folder(tmp)
        names = [model.data(model.index(i, 0),
                            QtCore.Qt.ItemDataRole.DisplayRole)
                 for i in range(model.rowCount())]
        self.assertEqual(["a.png", "b.obj", "c.hip"], names,
                         "hiding unknown files did not restore the "
                         "recognised-kinds-only view: %r" % names)

    def test_the_count_agrees_with_the_grid_in_both_states(self):
        from amaze.core import category
        tmp = self._folder()
        prefs = _Prefs([tmp])
        for show, expected in ((True, 5), (False, 3)):
            prefs.file_show_unknown = show
            folders_model = file_library.FileFolders(prefs)
            count = folders_model.data(
                folders_model.index(1, 0), category.SIDEBAR_COUNT_ROLE)
            self.assertEqual(
                expected, count,
                "show_unknown=%s: the sidebar says %s while the grid "
                "shows %s tiles" % (show, count, expected))

    def test_the_dialog_switch_writes_the_pref(self):
        from amaze.dialogs import prefs_dialog

        class _P:
            file_show_unknown = True
            saved = False

            def save(self):
                self.saved = True

        stub = type("_Stub", (), {})()
        stub._prefs = _P()
        prefs_dialog.PrefsDialog.set_file_show_unknown(stub, False)
        self.assertFalse(stub._prefs.file_show_unknown)
        self.assertTrue(stub._prefs.saved)


class ReviewFixesTest(unittest.TestCase):
    """The adversarial review round on the merge diff: five confirmed defects, one pin each."""

    def test_prefs_close_does_not_refresh_from_another_section(self):
        """The merged model's refresh can start the BLOCKING geometry render pass, so a prefs close must gate it on the File section actually showing - the next File activation rescans anyway."""
        import test_drag_gesture  # noqa: F401 - shares sys.path setup
        from amaze.panel import panel as panel_mod

        calls = []

        class _Model:
            def refresh_current_folder(self):
                calls.append("refresh")

        class _Panel:
            file_files_model = _Model()
            current_section = "material"
            prefs = None

        import inspect    # the pin is the GATE itself, source-checked - everything before it needs a constructed panel
        source = inspect.getsource(panel_mod.MatLibPanel._prefs_dialog_closed)
        self.assertIn('current_section == "file"', source,
                      "the refresh is not gated on the File section - "
                      "a prefs close can start the blocking geometry "
                      "pass from any tab")
        gate = source.index('current_section == "file"', 0)
        refresh = source.index('refresh_current_folder', 0)
        self.assertLess(gate, refresh,
                        "the gate sits after the refresh it must guard")

    def test_sidebar_count_agrees_with_the_grid(self):
        """The sidebar once counted subdirectories the grid never lists - 3 files + 2 subfolders reads 3, not 5."""
        tmp = tempfile.mkdtemp(prefix="amaze_count_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("a.png", "b.txt", "c.obj"):
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        os.makedirs(os.path.join(tmp, "sub_one"))
        os.makedirs(os.path.join(tmp, "sub_two"))
        prefs = _Prefs([tmp])
        folders_model = file_library.FileFolders(prefs)
        from amaze.core import category
        count = folders_model.data(
            folders_model.index(1, 0), category.SIDEBAR_COUNT_ROLE)
        self.assertEqual(3, count,
                         "the sidebar counts entries the grid never "
                         "shows (subdirectories)")

    def test_hidden_directories_are_pruned_from_the_recursive_scan(self):
        """The skip-hidden rule covers directories too, or Include Subfolders on a project folder floods the grid and the count with .git internals."""
        tmp = tempfile.mkdtemp(prefix="amaze_hidden_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "real.txt"), "w") as handle:
            handle.write("x")
        git = os.path.join(tmp, ".git", "objects")
        os.makedirs(git)
        with open(os.path.join(git, "abc123"), "w") as handle:
            handle.write("junk")
        prefs = _Prefs([tmp])
        prefs.set_file_folder_recursive(tmp, True)
        model = file_library.FileFiles(prefs)
        model.set_folder(tmp)
        names = [model.data(model.index(i, 0),
                            QtCore.Qt.ItemDataRole.DisplayRole)
                 for i in range(model.rowCount())]
        self.assertEqual(["real.txt"], names,
                         "the recursive scan descends into hidden "
                         "directories: %r" % names)
        folders_model = file_library.FileFolders(prefs)
        from amaze.core import category
        count = folders_model.data(
            folders_model.index(1, 0), category.SIDEBAR_COUNT_ROLE)
        self.assertEqual(1, count, "the count still includes hidden-"
                         "directory contents")

    def test_the_section_toggle_keeps_keys_it_does_not_know(self):
        """The Show/Hide rebuild keeps keys outside this build's registry - dropping them deletes an older build's tabs by side effect."""
        from amaze.dialogs import prefs_dialog

        class _P:
            enabled_sections = ["material", "texture", "geometry",
                                "hip", "file"]
            saved = False

            def save(self):
                self.saved = True

        stub = type("_Stub", (), {})()
        stub._prefs = _P()
        stub._section_boxes = {}
        for key in ("material", "gradient", "cop", "code", "file"):
            box = QtWidgets.QCheckBox()
            box.setChecked(key in ("material", "file"))
            stub._section_boxes[key] = box
        prefs_dialog.PrefsDialog._on_section_toggled(stub, False)
        self.assertEqual(["material", "file", "texture", "geometry",
                          "hip"], stub._prefs.enabled_sections,
                         "the rebuild dropped the dormant keys an "
                         "older build still lists its tabs from")
        self.assertTrue(stub._prefs.saved)

    def test_rerender_counts_distinct_keys_and_registers_them(self):
        """Two rows, one physical file, one key: the progress total counts distinct KEYS, and the freshly built key lands in _key_rows or its delivery repaints nothing and the disk cache is never written."""
        from unittest import mock
        from amaze.core import thumbnails
        prefs = _Prefs([])
        model = file_library.FileFiles(prefs)
        model._files = [("/a", "x.png"), ("/a", "x.png")]
        model._kinds = ["image", "image"]
        model._row_specs = [(None, "file", "/a/x.png"),
                            (None, "file", "/a/x.png")]
        with mock.patch.object(model, "_configure_engine_convert"), \
                mock.patch.object(
                    model, "_get_image_cache") as cache, \
                mock.patch.object(thumbnails.engine, "discard"), \
                mock.patch.object(thumbnails.engine, "request_convert"):
            cache.return_value.size = 256
            cache.return_value.invalidate = lambda full, flush=True: None    # `flush` too: rerender passes flush=False and writes the manifest once after the loop
            model.rerender_thumbnails([0, 1])
        self.assertEqual(1, model._progress_total,
                         "the total counts rows, not distinct keys - "
                         "the bar stalls short and the manifest flush "
                         "gated behind it never runs")
        key = ("tex", "/a/x.png", 256)
        self.assertEqual([0, 1], model._key_rows.get(key),
                         "the rerendered key is not registered - its "
                         "delivery finds no row to repaint and the "
                         "generated thumbnail never reaches the disk "
                         "cache")


class LocationColorTest(unittest.TestCase):
    """Locations carry colours like categories do: the sidebar answers the SAME role the asset sidebars answer so one delegate paints both, and the tile reads the colour of the location its file came from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_loccol_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "pic.exr"), "w") as handle:
            handle.write("x")
        self.prefs = _Prefs([self.tmp])

    def test_the_sidebar_answers_the_shared_colour_role(self):
        from amaze.core import category as category_mod
        folders = file_library.FileFolders(self.prefs)
        # Row 0 is "All" - a view, never coloured.
        self.assertFalse(folders.data(
            folders.index(0, 0), category_mod.SIDEBAR_COLOR_ROLE))
        row = folders.index(1, 0)
        self.assertEqual("", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))
        self.prefs.set_file_folder_color(self.tmp, "#4af2a1")
        self.assertEqual("#4af2a1", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))

    def test_a_tile_reports_its_location_colour(self):
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.tmp)
        self.assertTrue(files.rowCount(), "the fixture file was not scanned")
        index = files.index(0, 0)
        self.assertEqual("", files.data(index, files.CategoryColorRole))
        self.prefs.set_file_folder_color(self.tmp, "#4af2a1")
        self.assertEqual("#4af2a1",
                         files.data(index, files.CategoryColorRole))

    def test_the_role_number_matches_the_other_sections(self):
        """One delegate reads ONE number for every section - asserted against the LITERAL UserRole + 8, because MaterialLibrary sets its role in __init__ and a compare-to-Material check quietly compares FileFiles to itself."""
        from PySide6 import QtCore as _Qt
        from amaze.core import gradient_library as grad_mod
        expected = int(_Qt.Qt.ItemDataRole.UserRole) + 8
        self.assertEqual(expected,
                         int(file_library.FileFiles.CategoryColorRole))
        self.assertEqual(expected,
                         int(grad_mod.GradientLibrary.CategoryColorRole))


class ShowAllFilesTest(unittest.TestCase):
    """The per-location Show All Files override: one location can show its unknown files while the global preference hides them, and the sidebar count agrees with the grid either way."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_showall_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("pic.exr", "mystery.xyz"):
            with open(os.path.join(self.tmp, name), "w") as handle:
                handle.write("x")
        self.prefs = _Prefs([self.tmp])
        self.prefs.file_show_unknown = False

    def _grid_names(self):
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.tmp)
        return [files._files[row][1]
                for row in range(len(files._files))]

    def test_the_override_shows_what_the_global_hides(self):
        self.assertNotIn(
            "mystery.xyz", self._grid_names(),
            "with the global off and no override, the unknown file "
            "must stay hidden")
        self.prefs.set_file_folder_show_all(self.tmp, True)
        self.assertIn(
            "mystery.xyz", self._grid_names(),
            "the location's own Show All Files must override the "
            "global preference")

    def test_the_sidebar_count_agrees_per_location(self):
        folders = file_library.FileFolders(self.prefs)
        self.assertEqual(
            1, folders._folder_count(self.tmp),
            "hidden unknown files must leave the count too")
        self.prefs.set_file_folder_show_all(self.tmp, True)
        folders.refresh_counts()
        self.assertEqual(
            2, folders._folder_count(self.tmp),
            "a location showing all files must count all files")


class ABarePrefsLoadWritesNothingButItsOwnFile(unittest.TestCase):
    """`load()` may never write the library - the recovery-rehearsal helper loads LIVE settings by contract, and a load-time migration hook once moved a real machine's stars into the real library from a suite run; library-writing migrations run from product surfaces only."""

    def test_load_leaves_the_library_untouched(self):
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        lib = tempfile.mkdtemp(prefix="amaze_bareload_lib_")
        self.addCleanup(shutil.rmtree, lib, ignore_errors=True)
        home = tempfile.mkdtemp(prefix="amaze_bareload_home_")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "settings.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"directory": lib,
                       "library_user": test_support.FIXTURE_USER,
                       "material_favorites": ["mat-a"],
                       "file_folders": ["/somewhere/"]}, fh)
        p = prefs_module.Prefs()
        p.path = home
        p.load()
        self.assertEqual(
            [], os.listdir(lib),
            "a bare load() wrote the library - the exact write that "
            "moved live data out from under a suite run")
        self.assertIn(
            "material_favorites", p.data,
            "load() consumed the migration source itself - the doors "
            "own that, after a product surface asked for a favourite")


class AStarSurvivesTheMoveThroughTheModelDoors(unittest.TestCase):
    """The whole journey: star a scanned row, Locate the folder somewhere else, re-scan - the star is keyed to the location's id, so it never notices the path changed."""

    def test_the_star_is_still_lit_at_the_new_path(self):
        old = tempfile.mkdtemp(prefix="amaze_move_")
        self.addCleanup(shutil.rmtree, old, ignore_errors=True)
        open(os.path.join(old, "wood.png"), "w").close()
        prefs = _Prefs([old])
        folders_model = file_library.FileFolders(prefs)
        files = file_library.FileFiles(prefs)
        files.set_folder(old)
        self.assertEqual(1, files.rowCount(), "premise: one file scanned")
        files.toggle_favorite(0)
        self.assertTrue(files.index(0, 0).data(files.FavoriteRole),
                        "premise: the star lit")

        new = tempfile.mkdtemp(prefix="amaze_moved_")
        self.addCleanup(shutil.rmtree, new, ignore_errors=True)
        os.rename(os.path.join(old, "wood.png"),
                  os.path.join(new, "wood.png"))
        prefs.save = lambda: None
        self.assertGreaterEqual(folders_model.relocate_folder(1, new), 0,
                                "premise: the Locate landed")

        files.set_folder(new)
        self.assertEqual(1, files.rowCount(), "premise: the new scan sees it")
        self.assertTrue(
            files.index(0, 0).data(files.FavoriteRole),
            "the star did not survive the move - it was keyed to the "
            "path after all")


class ACountResolvesTheLocationRuleOnce(unittest.TestCase):
    """The sidebar count runs inside data(), the paint path - resolving the location record per FILE is a store get with a deepcopy, thousands of them on one first paint."""

    def test_the_rule_is_not_resolved_per_file(self):
        folder = tempfile.mkdtemp(prefix="amaze_count_cost_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        for i in range(12):
            open(os.path.join(folder, "f%d.png" % i), "w").close()
        prefs = _Prefs([folder])
        model = file_library.FileFolders(prefs)

        calls = []
        real = file_library.locations.record

        def counted(preferences, location):
            calls.append(location)
            return real(preferences, location)

        with mock.patch.object(file_library.locations, "record", counted):
            count = model._folder_count(folder)
        self.assertEqual(12, count, "premise: every file counted")
        self.assertLess(
            len(calls), 12,
            "the location rule was resolved per FILE (%d record reads "
            "for 12 files) - each is a store get with a deepcopy, on "
            "the paint path" % len(calls))


class AssetFavouritesMigrateIntoTheLibraryTest(unittest.TestCase):
    """`material_favorites` moves into the favourites store under the active user, SELF-MARKING: the key's presence is the to-do, it pops only after every id reads back out of the store, a deferral (no library, no user, Test Mode) leaves it authoritative, and the union is adopt-only."""

    def setUp(self):
        from amaze.core import keyed_store
        self.keyed_store = keyed_store
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.lib = tempfile.mkdtemp(prefix="amaze_favmig_lib_")
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def _store(self, p):
        return self.keyed_store.open_store(locations_mod.FAVOURITES_SPEC, p)

    def test_the_first_favourite_ask_moves_the_list_and_retires_the_key(self):
        p = _prefs_with_settings(self, {
            "directory": self.lib,
            "material_favorites": ["mat-a", "mat-b"]})
        self.assertIn(
            "material_favorites", p.data,
            "premise: load() left the list alone - migrating there "
            "made every load() caller a library writer")
        self.assertTrue(locations_mod.is_favourite(p, "mat-a"))    # the first favourite question a product surface asks is the trigger
        self.assertTrue(self._store(p).has("mat-a"))
        self.assertTrue(self._store(p).has("mat-b"))
        self.assertNotIn(
            "material_favorites", p.data,
            "the key survived a proven migration - the courtesy will "
            "carry it forever and re-run the union every launch")
        with open(os.path.join(p.path, "settings.json"),
                  encoding="utf-8") as handle:
            self.assertNotIn("material_favorites", json.load(handle),
                             "the retirement never reached disk")

    def test_without_a_user_the_list_waits_then_lands(self):
        p = _prefs_with_settings(self, {
            "directory": self.lib, "library_user": "",
            "material_favorites": ["mat-a"]})
        self.assertIn(
            "material_favorites", p.data,
            "the list was consumed with nobody to own it - the stars "
            "went into a blank tag or nowhere")
        p.library_user = "picked-uid"
        result = locations_mod.migrate_asset_favourites(p)
        self.assertEqual("migrated", result.get("state"))
        self.assertTrue(self._store(p).has("mat-a"))
        self.assertNotIn("material_favorites", p.data)

    def test_the_union_keeps_what_the_store_already_holds(self):
        p = _prefs_with_settings(self, {
            "material_favorites": ["mat-a", "mat-b"]})
        p.dir = self.lib
        self._store(p).set("mat-b", True)
        result = locations_mod.migrate_asset_favourites(p)
        self.assertEqual("migrated", result.get("state"))
        mine = self._store(p).all()
        self.assertEqual(
            {"mat-a", "mat-b"}, set(mine),
            "the union lost or duplicated a star between the settings "
            "list and what the store already held")

    def test_an_unstar_cannot_be_resurrected_by_the_pending_list(self):
        p = _prefs_with_settings(self, {
            "material_favorites": ["mat-a"]})
        p.dir = self.lib
        locations_mod.set_favourite(p, "mat-a", False)
        self.assertFalse(
            locations_mod.is_favourite(p, "mat-a"),
            "the unstar was resurrected - the write ran before the "
            "pending settings list was unioned in")
        self.assertNotIn("material_favorites", p.data)

    def test_the_paint_path_finishes_a_deferred_migration(self):
        p = _prefs_with_settings(self, {
            "material_favorites": ["mat-a"]})
        p.dir = self.lib
        self.assertTrue(
            locations_mod.is_favourite(p, "mat-a"),
            "a star still waiting in settings did not light once the "
            "library appeared - the paint path never retried")

    def test_test_mode_defers_and_keeps_the_list(self):
        test_lib = tempfile.mkdtemp(prefix="amaze_favmig_test_")
        self.addCleanup(shutil.rmtree, test_lib, ignore_errors=True)
        p = _prefs_with_settings(self, {
            "directory": self.lib, "test_mode": True,
            "test_dir": test_lib,
            "material_favorites": ["mat-a"]})
        self.assertIn(
            "material_favorites", p.data,
            "Test Mode consumed the real library's stars - they landed "
            "in the test library and the key is gone for the real one")
        self.assertFalse(
            self._store(p).has("mat-a"),
            "the star reached the TEST library's store")


class TheUserPickerFollowsTheLibrary(unittest.TestCase):
    """The users live IN the library, so switching libraries makes the open picker a list of the previous library's people - it showed them until Preferences was closed and reopened."""

    def _dialog_on_a_second_library(self):
        """A dialog open on library A, plus a ready library B whose only user has a name A does not have."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog

        first = test_support.fixture_prefs(self)
        dialog = prefs_dialog.PrefsDialog(first, panel=None)
        self.addCleanup(dialog.deleteLater)

        second = test_support.fresh_library(self)
        moved = test_support.fixture_prefs(self)
        moved.dir = second
        moved.library_user = ""
        users.current(moved)          # mints library B's first user
        theirs = users.name_for(moved, moved.library_user)
        return dialog, first, second, moved.library_user, theirs

    def test_the_premise_the_two_libraries_hold_different_people(self):
        """If the fixture gave both libraries the same user this proves nothing."""
        dialog, first, _second, uid_b, _name_b = self._dialog_on_a_second_library()
        from amaze.core import users
        self.assertNotIn(uid_b, users.all_users(first),
                         "both fixture libraries hold the same user")

    def test_changing_the_library_reloads_the_picker(self):
        dialog, first, second, uid_b, name_b = self._dialog_on_a_second_library()

        class _Panel:
            def __init__(self, prefs, path):
                self._prefs, self._path = prefs, path

            def set_library(self):
                self._prefs.dir = self._path      # what the real flow lands on

        dialog._panel = _Panel(first, second)
        dialog.change_library_path()

        listed = [dialog.cbb_library_user.itemData(i)
                  for i in range(dialog.cbb_library_user.count())]
        self.assertIn(
            uid_b, listed,
            "the picker still lists the OLD library's users after a "
            "switch - it only caught up when Preferences was reopened")

    def test_every_method_that_swaps_the_library_reloads_the_picker(self):
        """By AST over the whole dialog, so a THIRD way onto another library added later is caught too - not just the two known ones."""
        import ast
        import inspect
        from amaze.dialogs import prefs_dialog

        SWAPS = {"set_library", "switch_all_models"}
        tree = ast.parse(inspect.getsource(prefs_dialog))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            called = {
                inner.func.attr for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
            }
            if called & SWAPS and "_reload_library_users" not in called:
                offenders.append(node.name)
        self.assertEqual(
            [], offenders,
            "these change which library is live but leave the user "
            "picker showing the previous library's people: %s"
            % ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
