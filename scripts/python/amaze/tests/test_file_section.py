"""The File section merge's OWN inventions - the one-time prefs migration into the file_* quartet, the tab introducing itself once, `kind_for` routing, Copy Path's Houdini spelling, the OS-icon fallback, the per-kind double-click dispatch, and the hip drag (loads outside the panel, silent inside); the wider machinery stays pinned in test_hip_section, test_folder_sections, test_tile_icons and test_drag_gesture."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.actions import files as files_actions  # noqa: E402
from amaze.core import file_library  # noqa: E402
from amaze.core import locations as locations_mod  # noqa: E402
from amaze.core import tile_icons  # noqa: E402
from amaze.helpers import helpers, hostos  # noqa: E402
from amaze.panel import delegates  # noqa: E402
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

    def test_every_location_arrives_field_for_field_and_lands_in_the_library(self):
        prefs, library = self._prefs()
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
        self.assertEqual({"registered": True},    # registration alone, no decoration
                         locations_mod.record(prefs, "/tex/hdr/"))
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

    def test_a_lost_store_or_an_unreachable_library_serves_the_copy(self):
        """DECIDED: the last known list still shows, marked - the browser you want when a drive is gone."""
        for lost in (True, False):
            with self.subTest(lost_store=lost):
                prefs, library = self._prefs()
                if lost:    # migrated, then deleted: the .bak tier proves it WAS here, so it reads BLIND
                    self.assertEqual(6, len(prefs.file_folders))
                    os.remove(os.path.join(library, "locations.json"))
                    locations_mod.forget()
                else:
                    locations_mod.forget()
                    prefs.dir = os.path.join(library, "not-mounted")
                self.assertTrue(locations_mod.showing_last_known(prefs),
                                "an unreadable store or library is not "
                                "reported as such, so the sidebar cannot "
                                "mark it")
                self.assertEqual(
                    self.REAL_SHAPE["file_folders"], list(prefs.file_folders),
                    "the sidebar went empty although settings.json still "
                    "held every folder")
                self.assertEqual(
                    {"registered": True, "name": "Bokeh files", "recursive": True},
                    locations_mod.record(prefs, "/tex/bokeh/"),
                    "the copy lost the per-location facts")
                if not lost:
                    self.assertEqual(sorted(self.REAL_SHAPE["file_favorites"]),
                                     sorted(prefs.file_favorites))

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
        locations_mod._sync_mirror(prefs)    # the belt, driven directly: every write door refuses first
        self.assertEqual(
            dict(self.PRE_TAG_ROWS), dict(prefs.last_known_records),
            "the mirror blanked the copy from a scoped read that "
            "answers nothing - the fallback died while it was serving")

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

    def test_the_first_file_parm_takes_the_spelled_path_and_none_refuses(self):
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

    def test_an_image_becomes_a_mtlximage_and_a_sop_network_refuses_it(self):
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
        sop = self._geo()
        self.assertFalse(self.panel.sections["file"].create_image_node_in(
            self._index_for(home + "/x.png"), sop))
        self.assertEqual((), sop.children(),
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

    def test_a_vex_snippet_becomes_a_wrangle_in_sops_and_vops_refuse_it(self):
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
        vop = self._matnet()
        self.assertFalse(self.panel.sections["code"].create_code_node_in(index, vop),
                         "a VOP network took a VEX snippet")
        self.assertEqual((), vop.children())

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

    def test_the_click_dispatcher_absorbs_a_refusal_and_lets_a_crash_out(self):
        """A locked network's no is absorbed like a drop's; a programming error still crashes visibly."""
        from amaze.panel import sections as sections_module

        class RefusingSection:
            key = "refusing"
            DROP = sections_module.DropRule(
                click_resolve="refuse_for_the_test")

            def refuse_for_the_test(self, _index):
                raise hou.PermissionError(
                    "Cannot create a node inside a locked asset")

        class CrashingSection:
            key = "crashing"
            DROP = sections_module.DropRule(
                click_resolve="crash_for_the_test")

            def crash_for_the_test(self, _index):
                raise RuntimeError("a real defect")

        index = self.panel.code_sorted_model.index(0, 0)
        self.panel.click_on_row(RefusingSection(), index)
        with self.assertRaises(RuntimeError):
            self.panel.click_on_row(CrashingSection(), index)

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

    def test_the_selection_is_put_back_and_it_costs_no_undo_steps(self):
        """Selection calls push undo entries, so the restore runs under hou.undos.disabler()."""
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
        self.assertEqual((a,), hou.selectedNodes(),
                         "the block did not put the selection back")

    def test_a_selection_is_a_hint_the_click_and_the_menu_read_alike(self):
        """A selected node that cannot take the snippet falls through to creation; one that can, takes it."""
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        section = self.panel.sections["code"]
        for route, selected, children in (("click", "sphere", 2),
                                          ("menu", "sphere", 2),
                                          ("menu", "attribwrangle", 1)):
            with self.subTest(route=route, selected=selected):
                sop = self._geo()
                node = sop.createNode(selected)
                hou.clearAllSelected()
                node.setSelected(True)
                self._with_view_networks([sop])
                if route == "click":
                    self.panel.click_on_row(section, index)
                else:
                    section.menu_apply([index], index)    # the verb the menu table names
                wrangles = [c for c in sop.children()
                            if "wrangle" in c.type().name()]
                self.assertEqual(
                    (children, 1), (len(sop.children()), len(wrangles)),
                    "the %s door with a %s selected vetoed the creation, or "
                    "created beside a node that could take it"
                    % (route, selected))

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
        roles = {file_library.FileFiles.KindRole: locations_mod.KIND_GEO,
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
                            kind=locations_mod.KIND_IMAGE))
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


class HoudiniPathTest(unittest.TestCase):
    """Copy Path writes paths the way Houdini writes them."""

    def test_a_home_path_collapses_by_default_and_others_stay_absolute(self):
        """The default pins $HOME: a path under $HIP still says $HOME/... unless chosen otherwise."""
        self.assertEqual(
            "/mnt/somewhere/else.txt",
            helpers.houdini_path("/mnt/somewhere/else.txt"))
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        self.assertEqual(
            "$HOME/textures/wood.png",
            helpers.houdini_path(home + "/textures/wood.png"))
        self.assertEqual(
            home + "/x.png",
            helpers.houdini_path(home + "/x.png", "absolute"),
            "the absolute style collapsed")
        self.addCleanup(hou.putenv, "HIP", hou.text.expandString("$HIP"))
        hou.putenv("HIP", home + "/amaze_hip")    # its own $HIP: hython's is wherever the suite started
        collapsed = helpers.houdini_path(home + "/amaze_hip/render.exr")
        self.assertTrue(collapsed.startswith("$HOME/"),
                        "the default style is not $HOME: %r" % collapsed)

    def test_the_test_library_switch_rests_the_library_rows(self):
        """Test Library on: the Library and User rows rest, the Cache Path row stays live."""
        import os
        import shutil
        import tempfile
        from amaze.dialogs import prefs_dialog
        from amaze.prefs import prefs as prefs_mod

        p = test_support.fixture_prefs(self)
        real_library = p.dir
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        resting = (dlg.cbb_library, dlg._btn_add_library, dlg._btn_manage_libraries,
                   dlg.cbb_library_user)

        self.assertEqual("Test Library", dlg._cbx_test_mode.text())
        self.assertTrue(all(widget.isEnabled() for widget in resting),
                        "the Library rows start resting")
        self.assertEqual(real_library, dlg._picked_library())

        folder = tempfile.mkdtemp(prefix="amaze_switch_")
        self.addCleanup(shutil.rmtree, folder, True)
        prefs_mod.seed_test_folder(folder)
        p.test_dir = folder
        p.test_mode = True
        dlg._sync_test_mode_rows()

        self.assertEqual(
            test_support.posix_path(os.path.join(folder, "lib") + "/"),    # forward-slashed, as p.dir answers
            p.dir)
        self.assertEqual(real_library, dlg._picked_library(),
                         "the Library list left the real library")
        self.assertFalse(any(widget.isEnabled() for widget in resting
                             + (dlg._btn_apply_library, dlg._btn_accept_library)),
                         "a Library row is live while Test Library is on")
        self.assertTrue(dlg.line_cache.isEnabled(),
                        "the Cache Path row was frozen - the cache "
                        "does not move with the library")

        p.test_mode = False
        dlg._sync_test_mode_rows()
        self.assertEqual(real_library, p.dir,
                         "the real library did not come back")
        self.assertTrue(all(widget.isEnabled() for widget in resting))

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
        """The User row shows names, never UIDs, and makes nobody before Apply."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        p.library_user = ""
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(-1, dlg.cbb_library_user.currentIndex(),
                         "somebody was picked in a library with nobody in it")
        self.assertEqual({}, users.all_users(p), "opening Preferences made a user")
        dlg.create_library_user("  MyOwnName  ")
        self.assertEqual("MyOwnName", dlg.cbb_library_user.currentText())
        self.assertEqual({}, users.all_users(p), "a user was made before Apply")
        self.assertTrue(dlg.apply_library())
        uid = p.library_user
        self.assertEqual({uid: "MyOwnName"}, users.all_users(p),
                         "Apply did not make the user it showed")
        self.assertNotEqual("MyOwnName", uid,
                            "the pointer holds the NAME, not a UID")
        dlg.rename_library_user("Renamed")
        self.assertEqual("Renamed", users.name_for(p, uid),
                         "the rename did not relink the UID")
        self.assertEqual(uid, p.library_user,
                         "a RENAME minted a new identity")
        self.assertEqual("Renamed", dlg.cbb_library_user.currentText(),
                         "the dropdown still shows the old name")

    def test_the_user_row_switches_between_the_librarys_users_on_apply(self):
        """The User row lists the library's users; a pick switches this computer on Apply."""
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
        self.assertEqual(first, p.library_user,
                         "picking a user switched this computer before Apply")
        self.assertTrue(dlg.apply_library())
        self.assertEqual(second, p.library_user,
                         "Apply did not switch this computer to the picked user")

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
        if not locations_mod.record(self, old):
            return False
        return bool(locations_mod.relocate_record(self, old, new))    # the product door's body

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

    def set_file_folder_kinds(self, path, kinds):
        locations_mod.set_field(self, path, "kinds", sorted(set(kinds)))

    def set_file_folder_pathname(self, path, on):
        locations_mod.set_field(self, path, "pathname", bool(on) or None)


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
        self.assertEqual("", model.file_key(999))    # normpath("") is ".", truthy past every `if not key`
        self.assertEqual("", model.file_key(-1))

    def test_a_capture_taken_by_path_lands_on_the_tile(self):
        """The shelf names a scene by its path, the menu by its row: both reach one capture file."""
        from amaze.core import captures
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scene = os.path.join(tmp, "shot.hiplc")
        with open(scene, "w") as handle:
            handle.write("x")
        model = self._model_over(tmp)
        row = model.row_for_path(scene)
        self.assertGreaterEqual(row, 0, "the scene is not listed")
        key = captures.file_key(model.preferences, scene)
        self.assertTrue(key.startswith("loc:"), "the capture is keyed by path: %r" % key)
        self.assertEqual(model.tile_key(row), key)
        self.assertEqual(model.capture_path(row), captures.file_path(model.preferences, key))


class OsIconTest(unittest.TestCase):
    """A file Amaze does not recognise still gets a picture: the OS's own icon on a transparent tile-sized canvas, never scaled past 2x its native size (the recorded probe's caveat)."""

    def _model_with(self, *names):
        tmp = tempfile.mkdtemp(prefix="amaze_osicon_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in names:
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        model = file_library.FileFiles(_Prefs([tmp]))
        files_actions.connect(model, file_library.FileFolders(model.preferences),
                              os_icon=delegates.os_file_icon)    # as the panel does
        model.set_folder(tmp)
        return model

    def test_an_unknown_file_shows_the_file_face_until_preview_is_chosen(self):
        """T11 is the default for a file Amaze makes no preview of; its Preview is the system icon."""
        for name in ("mocap.bvh", "README"):
            with self.subTest(name=name):
                model = self._model_with(name)
                face = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
                self.assertEqual(tile_icons.generic_image("face_file"), face)
                with mock.patch.object(model, "tile_icon", return_value={"face": "preview"}):
                    shown = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
                self.assertIsNotNone(shown)
                self.assertFalse(shown.isNull(), "Preview drew a blank")
                if name == "README":    # no extension: the generic system icon, never blank
                    continue
                self.assertNotEqual(face, shown, "Preview still shows the file face")
                self.assertEqual(1, len(model._os_icons),
                                 "Preview did not ask for the system icon")

    def test_one_icon_is_composed_per_extension_not_per_file(self):
        model = self._model_with("a.log", "b.log", "c.log")
        with mock.patch.object(model, "tile_icon", return_value={"face": "preview"}):
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
                panel_mod.AmazePanel._apply_click_rule.__get__(recorder))
            section = sections.FileSection(recorder)
            section.create_image_node_in = (
                lambda index, network, position=None:
                recorder.calls.append("create_image_node_in") or True)
            section.open_hip_scene = (
                lambda index: recorder.calls.append("open_hip_scene"))
            panel_mod.AmazePanel.click_on_row(
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
            lambda p: panel_mod.AmazePanel._scene_path(recorder, p))
        panel_mod.AmazePanel.copy_file_paths(recorder, [
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

    def test_released_outside_the_panel_loads_and_inside_stays_silent(self):
        h = self._armed_hip()
        self._release_at_global(h, QtCore.QPoint(5000, 5000))
        self.assertIn("open", h.panel.calls,
                      "a hip dragged out of Amaze did not load")
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

    def test_plain_short_text_and_arithmetic_pass_through_untouched(self):
        """Escaping everything would turn `5 < 6` into `5 &lt; 6` on screen; Qt reads it as plain."""
        from amaze.helpers import ui_helpers
        for text in ("Short and sweet", "5 < 6 and 7 > 2"):
            with self.subTest(text=text):
                self.assertEqual(text, ui_helpers.tooltip_text(text))

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
        record = "\n".join(["<b>Free</b> Brick", "by <i>nobody</i>", "CC0"])    # the real sink
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
        self.assertIn("<br><br>Second paragraph.",
                      ui_helpers.tooltip_text(long + "\n\nSecond paragraph."),
                      "rich text ate the paragraph break")

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


class EveryDelegateCapsTheWordsItsItemsSay(unittest.TestCase):
    """Models answer plain words; the tile, the list cell and the sidebar row wrap them at the cap."""

    def _shown(self, delegate, words):
        """What `delegate` hands Qt's tooltip for an item answering `words`, or None."""
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("x")
        item.setToolTip(words)
        model.appendRow(item)
        view = QtWidgets.QListView()
        view.setModel(model)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 200, 200)
        point = QtCore.QPoint(150, 150)
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, point, point)
        with mock.patch.object(QtWidgets.QToolTip, "showText") as show:
            delegate.helpEvent(event, view, option, model.index(0, 0))
        return show.call_args[0][1] if show.called else None

    def test_a_long_tooltip_wraps_and_markup_shows_as_text(self):
        from amaze.helpers import ui_helpers
        from amaze.panel import delegates
        long = "word " * 300
        hostile = '<img src="http://evil.invalid/beacon.png">'    # an Online title is remote text
        for delegate in (test_support.tile_delegate({}), delegates.GridCellDelegate(),
                         delegates.SidebarItemDelegate()):
            for words in (long, hostile):
                with self.subTest(delegate=type(delegate).__name__, words=words[:10]):
                    self.assertEqual(ui_helpers.tooltip_text(words),
                                     self._shown(delegate, words))


class StarRowsLeftPreferencesTest(unittest.TestCase):
    """The badge family renders the favourite star AS DRAWN, so the star-colour rows left the dialog, the keys left the store, and the notes accent pinned to the theme's star token."""

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
        counts = _landed_counts(folders_model)[1:]
        self.assertEqual([2, 1], counts,
                         "the counts do not follow each location's own "
                         "recursion flag")

    def test_a_sidebar_paint_reads_the_location_list_once(self):
        """One read of the list serves a whole paint, and a write outside the model still shows."""
        model, prefs = self._folders_model(
            *[self._tmpdir() for _ in range(5)])
        self.assertEqual(6, model.rowCount(), "premise: five locations and All")
        reads = []
        real = locations_mod.registered_paths
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 QtCore.Qt.ItemDataRole.ToolTipRole, model.PathRole)
        with mock.patch.object(locations_mod, "registered_paths",
                               lambda p: (reads.append(1), real(p))[1]):
            for _paint in range(2):
                for row in range(model.rowCount()):
                    for role in roles:
                        model.data(model.index(row, 0), role)
            self.assertEqual([], reads, "two paints re-read the location "
                                        "list %d times" % len(reads))
            prefs.add_file_folder(self._tmpdir())
            self.assertEqual(7, model.rowCount(),
                             "a location registered outside the model "
                             "never reached it")

    def test_a_sidebar_paint_reads_each_location_record_once(self):
        """A name and a colour per row per paint come from one read per location, and an edit shows."""
        from amaze.core import category
        folders = [self._tmpdir() for _ in range(5)]
        model, prefs = self._folders_model(*folders)
        prefs.set_file_folder_name(folders[0], "Renamed")
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 category.SIDEBAR_COLOR_ROLE)

        def paint():
            return [[model.data(model.index(row, 0), role) for role in roles]
                    for row in range(1, model.rowCount())]

        reads = []
        real = locations_mod.record
        with mock.patch.object(locations_mod, "record",
                               lambda p, path: (reads.append(path),
                                                real(p, path))[1]):
            first = paint()
            paint()
            self.assertEqual(5, len(reads), "two paints of five locations "
                             "read %d records" % len(reads))
            self.assertEqual(["Renamed", ""], first[0],
                             "the paint lost the stored name")
            prefs.set_file_folder_color(folders[1], "#e0523a")
            self.assertEqual("#e0523a", paint()[1][1],
                             "a colour set outside the model never showed")

    def test_a_record_another_machine_wrote_shows_after_a_reread(self):
        """A reread at the Preferences door shows another writer's name and colour on the next paint."""
        from amaze.core import category, keyed_store
        folders = [self._tmpdir() for _ in range(2)]
        model, prefs = self._folders_model(*folders)
        prefs.set_file_folder_name(folders[0], "Mine")
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 category.SIDEBAR_COLOR_ROLE)

        def paint():
            return [model.data(model.index(1, 0), role) for role in roles]

        self.assertEqual(["Mine", ""], paint(), "premise: the stored name")
        key = locations_mod.LOC_PREFIX + locations_mod.location_id(
            prefs, folders[0])
        other = keyed_store.own_store(locations_mod.SPEC, prefs)
        self.assertTrue(other.set(key, dict(other.get(key), name="Theirs",
                                            color="#e0523a")),
                        "premise: the other writer did not save")
        self.assertEqual(["Mine", ""], paint(),
                         "premise: the file was read again before the door")
        self.assertIn(locations_mod.SPEC.filename,
                      keyed_store.refresh_all(prefs),
                      "premise: the door did not reread the locations file")
        self.assertEqual(["Theirs", "#e0523a"], paint(),
                         "the sidebar kept the record from before the reread")

    def test_with_counts_off_all_still_shows_the_total(self):
        """With counts off, All still shows its total once the walks the paint asked for land."""
        from amaze.panel import delegates
        folders = [self._tmpdir() for _ in range(3)]
        for n, folder in enumerate(folders):
            for i in range(n + 2):
                open(os.path.join(folder, "f%d.png" % i), "w").close()
        model, _prefs = self._folders_model(*folders)
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        delegate = delegates.SidebarItemDelegate(view)
        delegate.show_counts = False
        view.setItemDelegate(delegate)
        view.setModel(model)
        view.resize(260, 400)
        view.show()
        for _paint in range(3):
            view.grab()
        self.assertTrue(_pump_until(lambda: not model._walking),
                        "the walks the paint asked for never landed")
        texts = []
        for row in range(model.rowCount()):
            option = QtWidgets.QStyleOptionViewItem()
            option.widget = view
            option.font = view.font()
            delegate.initStyleOption(option, model.index(row, 0))
            texts.append(option.text)
        self.assertEqual("All (9)", texts[0],
                         "All lost its total with counts off: %s" % texts)
        self.assertEqual([model.display_name(path) for path in model._folders()],
                         texts[1:], "a hidden count was shown")

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

        prefs = _Prefs([])
        from amaze.core import captures    # a capture store with content that must survive
        capture_dir = captures.folder(prefs)
        os.makedirs(capture_dir, exist_ok=True)
        marker = os.path.join(capture_dir, "sweep_canary.png")
        with open(marker, "wb") as handle:
            handle.write(b"capture")
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)

        removed = file_library.sweep_folder_cache(
            prefs, doomed_dir, [kept_dir])
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

    def test_a_swept_entry_stays_gone_when_the_live_cache_saves(self):
        """The grid's own cache object held the removed folder's entries, saved and unsaved."""
        from amaze.core import texture_library
        doomed_dir = self._tmpdir()
        kept_dir = self._tmpdir()
        image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("red"))

        def source(folder, name):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(b"x")
            return hostos.canonical_path_key(path)

        saved, unsaved = (source(doomed_dir, n) for n in ("a.png", "b.png"))
        kept, later = (source(kept_dir, n) for n in ("c.png", "d.png"))
        cache = texture_library.ThumbnailCache(
            256, prefix="texture_thumbnails_sweep_live")
        self.addCleanup(shutil.rmtree, cache.cache_dir, ignore_errors=True)
        cache.put(saved, image)
        cache.put(kept, image)
        cache.save()
        cache.put(unsaved, image)
        prefs = _Prefs([])
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)

        file_library.sweep_folder_cache(prefs, doomed_dir, [kept_dir])
        cache.put(later, image)
        cache.save()

        with open(cache.manifest_path, encoding="utf-8") as handle:
            on_disk = sorted(json.load(handle))
        self.assertEqual(
            sorted([kept, later]), on_disk,
            "the live cache wrote the removed folder's entries back on "
            "its next save")
        self.assertFalse(
            os.path.exists(os.path.join(
                cache.cache_dir, cache._cache_filename(unsaved))),
            "a thumbnail the live cache had not saved yet outlived the "
            "sweep")

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


def _landed_counts(model, timeout=10.0):
    """Every row's count, All first, once no walk is queued or running; a paint only asks."""
    from amaze.core import category
    deadline = time.monotonic() + timeout
    while True:
        counts = [model.data(model.index(row, 0), category.SIDEBAR_COUNT_ROLE)
                  for row in range(model.rowCount())]
        if not getattr(model, "_walking", None) and None not in counts:
            return counts
        if time.monotonic() > deadline:
            raise AssertionError("the counts never landed: %s" % counts)
        _app.processEvents()
        time.sleep(0.002)


def _pump_until(done, timeout=10.0) -> bool:
    """Run the event loop until `done()` answers true, or the time is up."""
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.002)
    return bool(done())


class CountsWalkOffTheGuiThreadTest(unittest.TestCase):
    """The File sidebar's counts walk on a worker; a paint answers what is known now."""

    def _model(self, *sizes, recursive=()):
        """A sidebar over one fresh location per size, holding that many images each."""
        roots = []
        for n, size in enumerate(sizes):
            root = tempfile.mkdtemp(prefix="amaze_walk_")
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
            target = os.path.join(root, "sub") if n in recursive else root
            os.makedirs(target, exist_ok=True)
            for i in range(size):
                open(os.path.join(target, "f%d.png" % i), "w").close()
            roots.append(root)
        prefs = _Prefs(roots)
        for n in recursive:
            prefs.set_file_folder_recursive(roots[n], True)
        model = file_library.FileFolders(prefs)
        self.addCleanup(lambda: _pump_until(
            lambda: not getattr(model, "_walking", None)))
        return model, roots

    def _held_listing(self, held_root):
        """An `os.listdir` that holds a WORKER inside one location until released."""
        main = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        real = os.listdir

        def listing(path="."):
            if (threading.get_ident() != main
                    and str(path).rstrip("/") == held_root.rstrip("/")):
                entered.set()
                release.wait(10)
            return real(path)
        return listing, entered, release

    def test_a_paint_walks_no_folder_on_the_gui_thread(self):
        from amaze.panel import delegates
        model, roots = self._model(2, 3, recursive=(1,))
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        view.setItemDelegate(delegates.SidebarItemDelegate(view))
        main = threading.get_ident()
        on_gui = []

        def watched(real):
            def call(path="."):
                if (threading.get_ident() == main
                        and any(str(path).startswith(r) for r in roots)):
                    on_gui.append(str(path))
                return real(path)
            return call

        with mock.patch("os.listdir", watched(os.listdir)), \
                mock.patch("os.scandir", watched(os.scandir)):
            view.setModel(model)    # inside: the size hints ask for counts too
            view.resize(260, 200)
            view.show()
            view.grab()
            counts = _landed_counts(model)
        self.assertEqual([], on_gui, "a paint read folders on the GUI thread")
        self.assertEqual([5, 2, 3], counts, "the counts that landed are wrong")

    def test_counts_land_and_all_shows_the_total(self):
        from amaze.core import category
        model, _roots = self._model(2, 3, 4)
        changed = []
        model.dataChanged.connect(
            lambda first, last, roles=(): changed.append((first.row(), last.row())))
        first = [model.data(model.index(row, 0), category.SIDEBAR_COUNT_ROLE)
                 for row in range(model.rowCount())]
        self.assertEqual([None] * 4, first,
                         "a first paint answered counts only a walk could know")
        self.assertEqual([9, 2, 3, 4], _landed_counts(model),
                         "the counts or the All total did not land")
        for row in (0, 1, 2, 3):
            self.assertIn((row, row), changed,
                          "row %d was never told its count landed" % row)

    def test_a_held_location_holds_back_no_other_count(self):
        """A hung share holds only its own worker; every other location's count still lands."""
        model, roots = self._model(*[1] * 8)
        held_key = model._folders()[0]
        others = model._folders()[1:]
        listing, entered, release = self._held_listing(roots[0])
        with mock.patch("os.listdir", listing):
            for row in range(1, model.rowCount()):
                model.data(model.index(row, 0), model.COUNT_ROLE)
            landed = _pump_until(
                lambda: all(model._counts.get(p) == 1 for p in others), timeout=5.0)
            self.assertTrue(entered.is_set(), "premise: the held walk never ran on a worker")
            self.assertIsNone(model._counts.get(held_key),
                              "premise: the held location's count landed while held")
            waiting = [p for p in others if model._counts.get(p) is None]
            release.set()
            counts = _landed_counts(model)
        self.assertTrue(landed, "%d location(s) had no count while another walked: %s"
                        % (len(waiting), waiting))
        self.assertEqual([8] + [1] * 8, counts, "the counts that landed are wrong")

    def test_a_location_removed_mid_walk_keeps_no_count(self):
        model, roots = self._model(2, 3)
        doomed = model._folders()[0]
        listing, entered, release = self._held_listing(roots[0])
        with mock.patch("os.listdir", listing):
            model.data(model.index(1, 0), model.COUNT_ROLE)
            self.assertTrue(_pump_until(entered.is_set),
                            "the walk never ran on a worker")
            self.assertTrue(model.remove_folder(1), "premise: the remove refused")
            release.set()
            counts = _landed_counts(model)
        self.assertEqual([3, 3], counts, "All or the surviving row is wrong")
        self.assertNotIn(doomed, model._counts,
                         "the removed location kept the count its walk brought back")

    def test_a_count_walked_under_an_old_rule_is_dropped(self):
        """The location's Show All Files changes mid-walk: the walk lands stale, a fresh one counts."""
        root = tempfile.mkdtemp(prefix="amaze_walk_rule_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for name in ("a.png", "b.xyz"):
            open(os.path.join(root, name), "w").close()
        prefs = _Prefs([root])
        prefs.file_show_unknown = False
        model = file_library.FileFolders(prefs)
        key = model._folders()[0]
        shown = []
        model.dataChanged.connect(
            lambda first, last, roles=(): shown.append(model._counts.get(key)))
        listing, entered, release = self._held_listing(root)
        with mock.patch("os.listdir", listing):
            model.data(model.index(1, 0), model.COUNT_ROLE)
            self.assertTrue(_pump_until(entered.is_set),
                            "the walk never ran on a worker")
            prefs.set_file_folder_show_all(root, True)
            model.refresh_counts()
            release.set()
            counts = _landed_counts(model)
        self.assertEqual([2, 2], counts,
                         "a count walked under the old rule was kept")
        self.assertNotIn(1, shown, "the old rule's count was announced")

    def test_a_relocate_recounts_only_that_location(self):
        model, roots = self._model(1, 2, 3)
        _landed_counts(model)
        new = tempfile.mkdtemp(prefix="amaze_walk_moved_")
        self.addCleanup(shutil.rmtree, new, ignore_errors=True)
        for i in range(4):
            open(os.path.join(new, "g%d.png" % i), "w").close()
        model.preferences.save = lambda: None
        walked = []
        real = os.listdir

        def listing(path="."):
            if any(str(path).startswith(r) for r in roots + [new]):
                walked.append(str(path).rstrip("/"))
            return real(path)

        with mock.patch("os.listdir", listing):
            self.assertGreaterEqual(model.relocate_folder(2, new), 0,
                                    "premise: the Locate refused")
            counts = _landed_counts(model)
        self.assertEqual([8, 1, 4, 3], counts, "the moved location's count is wrong")
        self.assertEqual([new.rstrip("/")], walked,
                         "a Locate recounted locations it did not move")

    def test_a_count_asked_from_another_thread_still_lands(self):
        """hrpyc reads models off the GUI thread; a zero-timer armed there never fires."""
        model, _roots = self._model(5)
        asker = threading.Thread(
            target=lambda: model.data(model.index(1, 0), model.COUNT_ROLE))
        asker.start()
        asker.join(10)
        self.assertTrue(_pump_until(lambda: model._counts.get(model._folders()[0]) == 5),
                        "a count asked from another thread never landed")
        self.assertEqual([5, 5], _landed_counts(model),
                         "the sidebar stopped counting after an ask from another thread")

    def test_shutdown_does_not_wait_out_a_walk(self):
        """The stop flag is read between folders, so quitting mid-walk returns at once."""
        from amaze.core import folders as folders_mod
        root = tempfile.mkdtemp(prefix="amaze_walk_deep_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for i in range(40):
            os.makedirs(os.path.join(root, "d%02d" % i))
        prefs = _Prefs([root])
        prefs.set_file_folder_recursive(root, True)
        model = file_library.FileFolders(prefs)
        main = threading.get_ident()
        entered = threading.Event()
        real = os.scandir

        def slow(path="."):
            if threading.get_ident() != main and str(path).startswith(root):
                entered.set()
                time.sleep(0.25)    # 41 folders: about 10s for a walk nobody stops
            return real(path)

        with mock.patch("os.scandir", slow):
            model.data(model.index(1, 0), model.COUNT_ROLE)
            self.assertTrue(_pump_until(entered.is_set),
                            "the walk never ran on a worker")
            running = list(folders_mod.counter._threads)
            started = time.monotonic()
            folders_mod.counter.shutdown()
            elapsed = time.monotonic() - started
        _pump_until(lambda: not model._walking)
        self.assertTrue(running, "premise: no walk was running")
        self.assertLess(elapsed, 1.0, "shutdown waited %.2fs on a walk" % elapsed)
        self.assertFalse(any(t.isRunning() for t in running),
                         "a walk outlived the shutdown")
        self.assertEqual([], folders_mod._unstoppable,
                         "a walk had to be parked, so terminate() was reached")

    def test_a_shutdown_starts_none_of_the_queued_walks(self):
        """Walks the shutdown stopped hand nothing on; a later ask still counts every location."""
        from amaze.core import folders as folders_mod
        model, roots = self._model(*[1] * 6)
        main = threading.get_ident()
        walked = []
        real = os.listdir

        def listing(path="."):
            if (threading.get_ident() != main
                    and any(str(path).startswith(r) for r in roots)):
                walked.append(str(path))
                thread = QtCore.QThread.currentThread()
                deadline = time.monotonic() + 3
                while not thread.isInterruptionRequested() and time.monotonic() < deadline:
                    time.sleep(0.005)    # held until the shutdown stops it
            return real(path)

        with mock.patch("os.listdir", listing):
            for row in range(1, model.rowCount()):
                model.data(model.index(row, 0), model.COUNT_ROLE)
            self.assertTrue(_pump_until(lambda: len(walked) == model.COUNT_WORKERS),
                            "premise: the workers never all started")
            folders_mod.counter.shutdown()
            _pump_until(lambda: False, timeout=0.3)    # every stopped walk's end is handled
            started = list(walked)
        self.assertEqual(model.COUNT_WORKERS, len(started),
                         "the stopped walks started the queued ones after the shutdown")
        self.assertEqual([6] + [1] * 6, _landed_counts(model),
                         "after a shutdown the counts never landed")


class RemovingANestedLocationTest(unittest.TestCase):
    """A file a remaining location still lists keeps its comment, star and icon."""

    ICON = {"name": "activity", "bg": "#ff8000"}

    def setUp(self):
        self.outer = tempfile.mkdtemp(prefix="amaze_outer_")
        self.addCleanup(shutil.rmtree, self.outer, ignore_errors=True)
        self.inner = os.path.join(self.outer, "tex")
        self.file = os.path.join(self.inner, "plate.txt")
        os.makedirs(self.inner)
        with open(self.file, "w") as handle:
            handle.write("x")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)

    def _nested(self, *folders):
        prefs = _Prefs(folders)
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)
        if self.outer in folders:
            prefs.set_file_folder_recursive(self.outer, True)
        return prefs

    def _row(self, prefs, folder):
        model = file_library.FileFiles(prefs)
        model.set_folder(folder)
        names = [model.data(model.index(row, 0)) for row in
                 range(model.rowCount())]
        return model, names.index("plate.txt")

    def _annotate(self, prefs):
        from amaze.core import notes
        model, row = self._row(prefs, self.inner)
        key = model.file_key(row)
        model.toggle_favorite(row)
        model.set_tile_icon(row, self.ICON)
        notes.set_note(prefs, notes.note_key("file", key),
                       [{"t": "text", "text": "kept"}])
        return key

    def _shown(self, prefs, folder):
        model, row = self._row(prefs, folder)
        index = model.index(row, 0)
        return (model.data(index, model.FavoriteRole),
                model.data(index, model.NotesRole),
                model.tile_icon(row).get("name"))

    def _remove(self, prefs, folder):
        listed = [hostos.canonical_path_key(p) for p in prefs.file_folders]
        file_library.FileFolders(prefs).remove_folder(
            listed.index(hostos.canonical_path_key(folder)) + 1)
        self.assertNotIn(
            hostos.canonical_path_key(folder),
            [hostos.canonical_path_key(p) for p in prefs.file_folders],
            "premise: the location is still registered")

    def test_the_outer_location_keeps_the_comment_star_and_icon(self):
        prefs = self._nested(self.outer, self.inner)
        key = self._annotate(prefs)
        inner_id = locations_mod.location_id(prefs, self.inner)
        self.assertTrue(key.startswith("loc:" + inner_id + "/"),
                        "premise: the nested location does not own the file")
        prefs.library_user = LocationsArePerUserTest.OTHER
        locations_mod.set_favourite(prefs, key, True)
        prefs.library_user = test_support.FIXTURE_USER

        self._remove(prefs, self.inner)

        self.assertEqual(
            (True, True, "activity"), self._shown(prefs, self.outer),
            "removing the nested location retired the star, comment or "
            "icon of a file the outer location still lists")
        prefs.library_user = LocationsArePerUserTest.OTHER
        self.assertTrue(
            locations_mod.is_favourite(
                prefs, locations_mod.file_ident(prefs, self.file)),
            "another user's star on that file was retired")

    def test_a_location_nothing_else_covers_still_loses_them(self):
        from amaze.core import notes
        prefs = self._nested(self.inner)
        key = self._annotate(prefs)

        self._remove(prefs, self.inner)

        self.assertEqual(
            (False, False, {}),
            (locations_mod.is_favourite(prefs, key),
             notes.has_note(prefs, notes.note_key("file", key)),
             tile_icons.override_for(prefs, key)),
            "a removed location no other location covers kept a star, "
            "comment or icon, so re-adding it is not a clean slate")

    def test_a_refused_move_retires_nothing(self):
        from amaze.core import keyed_store
        prefs = self._nested(self.outer, self.inner)
        self._annotate(prefs)
        real = keyed_store.Store.rekey_stored

        def refuse_comments(store, moves):
            if store.spec.filename == "notes.json":
                return keyed_store.Written(False, keyed_store.REASON_DENIED)
            return real(store, moves)

        with mock.patch.object(keyed_store.Store, "rekey_stored",
                               refuse_comments):
            self._remove(prefs, self.inner)

        self.assertEqual(
            (True, True, "activity"), self._shown(prefs, self.outer),
            "a comment that could not move was retired anyway")

    def test_a_key_spelled_as_a_path_moves_too(self):
        from amaze.core import keyed_store, notes
        prefs = self._nested(self.outer, self.inner)
        spelled = hostos.storage_path_key(self.file)
        stores = [keyed_store.open_store(spec, prefs) for spec in
                  (locations_mod.FAVOURITES_SPEC, notes.SPEC, tile_icons.SPEC)]
        stores[0]._table[test_support.FIXTURE_USER + "|" + spelled] = {
            "favourite": True}
        stores[1]._table["file:" + spelled] = {
            "items": [{"t": "text", "text": "kept"}]}
        stores[2]._table[spelled] = tile_icons.normalise(self.ICON)

        self.assertTrue(locations_mod.rehome_covered(prefs, self.inner))

        moved = ("loc:" + locations_mod.location_id(prefs, self.outer)
                 + "/tex/plate.txt")
        self.assertEqual(
            [True, True, True],
            [store.has(prefix + moved) for store, prefix in
             zip(stores, ("", "file:", ""))],
            "a path-spelled key the outer location covers stayed behind "
            "for the retire")


class TheFolderOrderHasOneSpellingTest(unittest.TestCase):
    """Locations under home store as `~/...`; the order copy must match them however it was written."""

    def setUp(self):
        self.home = hostos.canonical_path_key(
            tempfile.mkdtemp(prefix="amaze_home_"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        patcher = mock.patch.object(hostos, "_home_root",
                                    return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _under_home(self, name):
        path = os.path.join(self.home, name)
        os.makedirs(path)
        return path

    def _listed(self, prefs):
        return [hostos.canonical_path_key(p) for p in prefs.file_folders]

    def test_an_offline_remove_takes_the_row_off(self):
        prefs, library = _location_prefs(self, {})
        folder = self._under_home("tex")
        prefs.add_file_folder(folder)
        self.assertIn(hostos.canonical_path_key(folder), self._listed(prefs),
                      "premise: the location did not register")
        locations_mod.forget()
        prefs.dir = os.path.join(library, "not-mounted")
        self.assertTrue(locations_mod.showing_last_known(prefs),
                        "premise: the library still answers")
        prefs.remove_file_folder(folder)
        self.assertNotIn(
            hostos.canonical_path_key(folder), self._listed(prefs),
            "removing a location while the library is unreachable left "
            "its row - the order copy holds another spelling of it")

    def test_a_remove_with_no_library_after_a_restart_takes_the_row_off(self):
        prefs = _prefs_with_settings(self, {
            "directory": "",
            "file_folders": ["~/tex/"],
            "file_location_records": {"~/tex/": {"registered": True}},
        })
        folder = self._under_home("tex")
        self.assertEqual([hostos.canonical_path_key(folder)],
                         self._listed(prefs),
                         "premise: the stored location did not load")
        prefs.remove_file_folder(prefs.file_folders[0])
        self.assertEqual([], self._listed(prefs),
                         "a location read back from settings could not be "
                         "removed with no library configured")

    def test_locate_after_a_reorder_keeps_the_row(self):
        prefs, _library = _location_prefs(self, {})
        for name in ("a", "b", "c"):
            prefs.add_file_folder(self._under_home(name))
        model = file_library.FileFolders(prefs)
        self.assertTrue(model.move_folder(3, 1), "premise: no reorder")
        moved = self._under_home("c_moved")
        self.assertGreaterEqual(model.relocate_folder(1, moved), 0,
                                "premise: Locate refused")
        self.assertEqual(
            hostos.canonical_path_key(moved), self._listed(prefs)[0],
            "Locate after a reorder dropped the location to the bottom "
            "of the sidebar")


class ALocationWriteIsAnnouncedOnlyWhenItLandsTest(unittest.TestCase):
    """The sidebar hears about a row only after its prefs write landed."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_landed_")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        with open(os.path.join(self.folder, "plate.txt"), "w") as handle:
            handle.write("x")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.prefs = _Prefs([self.folder])
        self.addCleanup(shutil.rmtree, self.prefs.dir, ignore_errors=True)
        self.model = file_library.FileFolders(self.prefs)
        self.heard = []
        for name in ("rowsAboutToBeInserted", "rowsInserted",
                     "rowsAboutToBeRemoved", "rowsRemoved", "modelReset"):
            getattr(self.model, name).connect(
                lambda *args, name=name: self.heard.append(
                    (name, self.model.rowCount())))

    def _refused(self):
        from amaze.core import keyed_store
        real = keyed_store.Store._commit

        def refuse_locations(store, staged, keys, retire=()):
            if store.spec.filename == locations_mod.LOCATIONS_FILE:
                return keyed_store.Written(False, keyed_store.REASON_DENIED)
            return real(store, staged, keys, retire)

        return mock.patch.object(keyed_store.Store, "_commit",
                                 refuse_locations)

    def test_a_refused_remove_or_add_changes_and_announces_nothing(self):
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.folder)
        files.toggle_favorite(0)
        key = files.file_key(0)
        with self._refused():
            landed = self.model.remove_folder(1)
        self.assertTrue(locations_mod.is_favourite(self.prefs, key),
                        "a refused removal retired the star of a file the "
                        "location still lists")
        self.assertEqual(
            [hostos.canonical_path_key(self.folder)],
            [hostos.canonical_path_key(p) for p in self.prefs.file_folders],
            "a refused removal still took the location off the list")
        self.assertEqual([], self.heard,
                         "the sidebar was told a row left that is still "
                         "there")
        self.assertFalse(landed)
        other = tempfile.mkdtemp(prefix="amaze_landed_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with self._refused():
            landed = self.model.add_folder(other)
        self.assertEqual([], self.heard,
                         "the sidebar was told about a row the refused "
                         "write never made")
        self.assertFalse(landed)
        self.assertEqual(2, self.model.rowCount())

    def test_a_landed_write_is_announced_around_the_change(self):
        other = tempfile.mkdtemp(prefix="amaze_landed_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertTrue(self.model.add_folder(other))
        self.assertTrue(self.model.remove_folder(1))
        self.assertEqual(
            [("rowsAboutToBeInserted", 2), ("rowsInserted", 3),
             ("rowsAboutToBeRemoved", 3), ("rowsRemoved", 2)],
            self.heard,
            "a row change was not bracketed: the model must answer the "
            "old rows until the views are told")


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
        from amaze.actions import clean
        clean.clean_folders_and_favorites(panel.prefs, panel.file_folders_model)

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


class CleanUpLibraryReachesTheFoldersTest(unittest.TestCase):
    """Clean Up Library's one pass ends with the folder pointers, not only the asset lists."""

    def test_a_dead_location_is_dropped_and_reported(self):
        from amaze.actions import clean
        panel = test_support.fixture_panel(self)
        dead = tempfile.mkdtemp(prefix="amaze_dead_location_")
        self.addCleanup(shutil.rmtree, dead, ignore_errors=True)
        self.addCleanup(panel.prefs.remove_file_folder, dead)
        panel.file_folders_model.add_folder(dead)
        shutil.rmtree(dead)

        sections = clean.clean_library(
            panel.prefs, panel.material_model, panel.category_model,
            panel.cop_model, panel.cop_category_model, panel.file_folders_model)

        self.assertNotIn(hostos.canonical_path_key(dead), list(panel.prefs.file_folders),
                         "Clean Up Library left a location whose folder is gone")
        self.assertTrue([s for s in sections if s.startswith("Folders and favorites:")],
                        "the report does not say which locations went")


class CleanupPrunesOnlyFileFavouritesTest(unittest.TestCase):
    """The favourites store holds every section's stars; only a File one names a file to check."""

    def test_a_material_star_survives_and_a_dead_file_star_goes(self):
        panel = test_support.fixture_panel(self)
        model = panel.material_model
        mat_id = model.assets[1].mat_id    # row 0 is the fixture's odd id -1
        model.toggle_fav(1)
        self.assertTrue(locations_mod.is_favourite(panel.prefs, mat_id),
                        "premise: the material star did not set")
        dead = os.path.join(panel.prefs.file_folders[0], "gone.exr")
        panel.prefs.add_file_favorite(dead)
        self.assertTrue(locations_mod.is_favourite(panel.prefs, dead),
                        "premise: the File star did not set")

        from amaze.actions import clean
        lines = clean.clean_folders_and_favorites(panel.prefs, panel.file_folders_model)

        self.assertTrue(
            locations_mod.is_favourite(panel.prefs, mat_id),
            "Clean Library removed a material's star - its bare asset id "
            "was checked as a file path, and no file is named like an id")
        self.assertNotIn(str(mat_id), "\n".join(lines),
                         "the report lists a material id as a gone file")
        self.assertFalse(locations_mod.is_favourite(panel.prefs, dead),
                         "a favourite whose file is gone survived Clean")

    def test_the_offline_copy_lists_no_asset_star_as_a_file(self):
        shape = LocationsFollowTheLibraryTest.REAL_SHAPE
        prefs, library = _location_prefs(self, shape)
        mat_id = "139888336268658010"
        self.assertTrue(locations_mod.set_favourite(prefs, mat_id, True))
        self.assertIn(
            test_support.FIXTURE_USER + "|" + mat_id,
            prefs.last_known_favourites,
            "premise: the mirror did not copy the material star")
        locations_mod.forget()
        prefs.dir = os.path.join(library, "not-mounted")
        self.assertTrue(locations_mod.showing_last_known(prefs),
                        "premise: the library still answers")

        self.assertEqual(
            sorted(shape["file_favorites"]), sorted(prefs.file_favorites),
            "the offline copy hands a material id to the File favourites")


class ShowUnknownFilesSwitchTest(unittest.TestCase):
    """`file_show_unknown`, read by a location saved before Show ▸: the count agrees either way."""

    def _folder(self):
        tmp = tempfile.mkdtemp(prefix="amaze_unknown_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("a.png", "b.obj", "c.hip", "d.bvh", "e.txt"):
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        return tmp

    def test_the_default_shows_everything_and_off_shows_the_known_kinds(self):
        self.assertTrue(prefs_module.Prefs().file_show_unknown,
                        "the default hides files - the merge's whole "
                        "point was a folder showing what is in it")
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
        tmp = self._folder()
        prefs = _Prefs([tmp])
        for show, expected in ((True, 5), (False, 3)):
            prefs.file_show_unknown = show
            folders_model = file_library.FileFolders(prefs)
            count = _landed_counts(folders_model)[1]
            self.assertEqual(
                expected, count,
                "show_unknown=%s: the sidebar says %s while the grid "
                "shows %s tiles" % (show, count, expected))


class ShowTicksTest(unittest.TestCase):
    """Show ▸'s kinds combine freely: a location lists exactly what is ticked, and counts it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_show_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("a.png", "b.obj", "c.hip", "d.txt"):
            with open(os.path.join(self.tmp, name), "w") as handle:
                handle.write("x")
        self.prefs = _Prefs([self.tmp])

    def _listed(self, kinds):
        self.prefs.set_file_folder_kinds(self.tmp, kinds)
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp)
        names = sorted(model._files[row][1] for row in range(len(model._files)))
        count = _landed_counts(file_library.FileFolders(self.prefs))[1]
        self.assertEqual(len(names), count, "the sidebar counts what the grid does not list")
        return names

    def test_each_combination_lists_exactly_its_kinds(self):
        image, geo, hip, other = (locations_mod.KIND_IMAGE, locations_mod.KIND_GEO,
                                  locations_mod.KIND_HIP, locations_mod.KIND_OTHER)
        for kinds, expected in (
                ((image,), ["a.png"]),
                ((image, other), ["a.png", "d.txt"]),
                ((geo, hip), ["b.obj", "c.hip"]),
                ((image, geo, hip, other), ["a.png", "b.obj", "c.hip", "d.txt"]),
                ((), [])):
            with self.subTest(kinds=kinds):
                self.assertEqual(expected, self._listed(kinds))

    def test_a_location_saved_before_Show_keeps_what_it_showed(self):
        """No ticks: the three known kinds, plus Other Files where the old rule showed all files."""
        known = set(locations_mod.SHOWN_BY_DEFAULT)
        for show_unknown, override, expected in (
                (True, None, known | {locations_mod.KIND_OTHER}),
                (False, None, known),
                (False, True, known | {locations_mod.KIND_OTHER}),
                (True, False, known)):
            with self.subTest(show_unknown=show_unknown, override=override):
                self.prefs.file_show_unknown = show_unknown
                self.prefs.set_file_folder_show_all(self.tmp, override)
                self.assertEqual(expected, set(
                    file_library.location_kinds(self.prefs, self.tmp)))

    def test_pathname_names_the_row_by_its_path_even_over_a_rename(self):
        self.prefs.path_style = "absolute"
        folders = file_library.FileFolders(self.prefs)
        folder = os.path.basename(self.tmp.rstrip("/\\"))
        self.assertEqual(folder, folders.display_name(self.tmp))
        self.prefs.set_file_folder_pathname(self.tmp, True)
        path = helpers.houdini_path(self.tmp, "absolute")
        self.assertEqual(path, folders.display_name(self.tmp))
        self.prefs.set_file_folder_name(self.tmp, "Textures")
        self.assertEqual(path, folders.display_name(self.tmp),
                         "a renamed folder kept its name with Pathname ticked")
        self.prefs.set_file_folder_pathname(self.tmp, False)
        self.assertEqual("Textures", folders.display_name(self.tmp))


class ANewLocationStartsWithTheKnownKindsTest(unittest.TestCase):
    """Add ticks Images, Geometry and HIP; a folder added again keeps its own ticks."""

    def test_add_ticks_the_three_known_kinds(self):
        prefs, _library = _location_prefs(self, {})
        folder = tempfile.mkdtemp(prefix="amaze_new_loc_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        prefs.add_file_folder(folder)
        self.assertEqual(set(locations_mod.SHOWN_BY_DEFAULT),
                         set(file_library.location_kinds(prefs, folder)))
        prefs.set_file_folder_kinds(folder, (locations_mod.KIND_OTHER,))
        prefs.add_file_folder(folder)
        self.assertEqual({locations_mod.KIND_OTHER},
                         set(file_library.location_kinds(prefs, folder)),
                         "adding a folder again reset what it shows")


class ReviewFixesTest(unittest.TestCase):
    """The adversarial review round on the merge diff: five confirmed defects, one pin each."""

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
        count = _landed_counts(folders_model)[1]
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
        count = _landed_counts(folders_model)[1]
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


class _EscDuringTheFirstRender:
    """A geometry pass whose user presses Esc while the first file renders."""

    def __init__(self, *args, **kwargs):
        self.ticks = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def updateProgress(self, fraction=-1.0):
        self.ticks += 1
        if self.ticks > 1:
            raise hou.OperationInterrupted()


class GeometryThatRendersNothingIsRememberedTest(unittest.TestCase):
    """A geometry file that yields no picture waits for a change or Rerender Thumbnail."""

    def _geometry(self):
        folder = tempfile.mkdtemp(prefix="amaze_geo_none_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "rig.fbx")
        with open(path, "w") as handle:
            handle.write("no cookable geometry")
        prefs = _Prefs([folder])
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)
        model = file_library.FileFiles(prefs)
        files_actions.connect(model, file_library.FileFolders(prefs))    # its render, as the panel hands it
        return folder, path, model

    def _rendering(self, rendered):
        from amaze.render import thumbs

        def nothing(_renderer, path, out_path, size):
            rendered.append(path)
            return False

        return mock.patch.object(
            thumbs.ThumbNailRenderer, "create_thumb_geo_file", nothing)

    def test_a_file_that_renders_nothing_is_not_rendered_again(self):
        folder, _path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            1, len(rendered),
            "a geometry file that yielded no thumbnail went through the "
            "blocking render pass again on the next visit")

    def test_a_change_or_rerender_tries_again(self):
        folder, path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.rerender_thumbnails([0])
            with open(path, "a") as handle:
                handle.write(" - edited")
            model.set_folder(folder)
        self.assertEqual(3, len(rendered),
                         "Rerender Thumbnail or an edited file did not "
                         "get another render")

    def test_a_rendered_picture_reaches_the_cache(self):
        """The renderer writes through Houdini's own image writer, which picks the format from the name."""
        folder, path, model = self._geometry()
        from amaze.render import thumbs

        def picture(_renderer, _path, out_path, _size):
            hou.saveImageDataToFile([1.0, 0.0, 0.0, 1.0] * 4, 2, 2, out_path)
            return True

        with mock.patch.object(
                thumbs.ThumbNailRenderer, "create_thumb_geo_file", picture):
            model.set_folder(folder)
        cache = model._get_geo_cache()
        self.assertFalse(
            cache.known_failure(path),
            "a render that wrote a picture was remembered as a file with no "
            "geometry: the scratch name made Houdini write a format Qt cannot read")
        self.assertIsNotNone(cache.valid_path(path),
                             "the rendered picture never reached the cache")

    def test_a_failure_an_older_build_recorded_is_tried_again(self):
        folder, path, model = self._geometry()
        cache = model._get_geo_cache()
        st = os.stat(path)
        cache._manifest[cache._key(path)] = {
            "mtime": st.st_mtime, "size": st.st_size, "failed": True}
        cache.save()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            1, len(rendered),
            "an untagged failure from the build whose scratch Qt could not "
            "read kept the file unpictured, or the retry was not remembered")

    def test_an_interrupted_render_is_not_remembered(self):
        folder, _path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            with mock.patch.object(hou, "InterruptableOperation",
                                   _EscDuringTheFirstRender):
                model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            2, len(rendered),
            "an Esc during a render was remembered as a file with no "
            "geometry, so it never renders again")


class LocationColorTest(unittest.TestCase):
    """Locations carry colours like categories do: the sidebar answers the SAME role the asset sidebars answer so one delegate paints both, and the tile reads the colour of the location its file came from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_loccol_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "pic.exr"), "w") as handle:
            handle.write("x")
        self.prefs = _Prefs([self.tmp])

    def test_the_sidebar_and_the_tile_answer_the_locations_colour(self):
        from amaze.core import category as category_mod
        folders = file_library.FileFolders(self.prefs)
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.tmp)
        self.assertTrue(files.rowCount(), "the fixture file was not scanned")
        # Row 0 is "All" - a view, never coloured.
        self.assertFalse(folders.data(
            folders.index(0, 0), category_mod.SIDEBAR_COLOR_ROLE))
        row = folders.index(1, 0)
        index = files.index(0, 0)
        self.assertEqual("", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))
        self.assertEqual("", files.data(index, files.CategoryColorRole))
        self.prefs.set_file_folder_color(self.tmp, "#4af2a1")
        self.assertEqual("#4af2a1", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))
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

    def test_the_override_shows_what_the_global_hides_and_counts_it(self):
        folders = file_library.FileFolders(self.prefs)
        self.assertNotIn(
            "mystery.xyz", self._grid_names(),
            "with the global off and no override, the unknown file "
            "must stay hidden")
        self.assertEqual(
            1, _landed_counts(folders)[1],
            "hidden unknown files must leave the count too")
        self.prefs.set_file_folder_show_all(self.tmp, True)
        self.assertIn(
            "mystery.xyz", self._grid_names(),
            "the location's own Show All Files must override the "
            "global preference")
        folders.refresh_counts()
        self.assertEqual(
            2, _landed_counts(folders)[1],
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
        theirs = "Theirs"
        return dialog, first, second, users.create(moved, theirs), theirs

    def test_picking_a_library_lists_its_users(self):
        from amaze.core import users
        dialog, first, second, uid_b, name_b = self._dialog_on_a_second_library()
        self.assertNotIn(uid_b, users.all_users(first),
                         "premise: both fixture libraries hold the same user")
        dialog.pick_library(second)
        listed = [dialog.cbb_library_user.itemData(i)
                  for i in range(dialog.cbb_library_user.count())]
        self.assertIn(uid_b, listed,
                      "the picker still lists the open library's users")
        self.assertEqual(uid_b, dialog.cbb_library_user.currentData(),
                         "the library's only user was not picked")

    def test_every_method_that_swaps_the_library_reloads_the_picker(self):
        """By AST over the whole dialog, so a THIRD way onto another library added later is caught too - not just the two known ones."""
        import ast
        import inspect
        from amaze.dialogs import prefs_dialog

        SWAPS = {"set_library", "switch_all_models", "open_library"}
        tree = ast.parse(inspect.getsource(prefs_dialog))
        offenders = []
        door = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            called = {
                inner.func.attr for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
            }
            if node.name == "_sync_rows":
                door = called
            if called & SWAPS and "_sync_rows" not in called:
                offenders.append(node.name)
        self.assertIn("_reload_library_users", door,
                      "the door every library change takes no longer "
                      "reloads the user picker")
        self.assertEqual(
            [], offenders,
            "these change which library is live but leave the user "
            "picker showing the previous library's people: %s"
            % ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
