"""The File section merge (2026-07-31): what only exists because of it.

The wider machinery is pinned where it always was - test_hip_section
for captures and scene rows, test_folder_sections for the caches and
scan order, test_tile_icons for the icon wiring, test_drag_gesture for
the release dispatch. THIS file pins the merge's own inventions:

* the one-time prefs migration (three sections' collections union into
  the file_* quartet, idempotently, with the old keys left for the
  older build on the other machine),
* the 'file' tab introducing itself exactly once,
* kind_for - the router every per-type behaviour hangs off,
* Copy Path as a HOUDINI path ($HIP/$JOB/$HOME - the sheet's rule),
* the OS icon for a file Amaze does not recognise (never empty - the
  recorded QFileIconProvider probe),
* the per-kind double-click dispatch,
* and the hip drag: released outside the panel it loads the scene,
  released inside it stays silent.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

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


def _prefs_with_settings(testcase, settings: dict):
    """A Prefs whose settings.json holds exactly `settings`, loaded."""
    home = tempfile.mkdtemp(prefix="amaze_file_prefs_")
    testcase.addCleanup(shutil.rmtree, home, ignore_errors=True)
    with open(os.path.join(home, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump(settings, handle)
    p = prefs_module.Prefs()
    p.path = home
    p.load()
    return p


class MigrationTest(unittest.TestCase):
    """The three merged sections' collections become the File
    section's, ONCE, and nothing of the old surface is destroyed."""

    #: What a pre-merge settings.json carries. Portable-encoded paths
    #: are what the codec writes; plain absolutes decode fine too.
    OLD = {
        "texture_folders": ["/tex/a/", "/shared/b/"],
        "geometry_folders": ["/geo/c/", "/shared/b/"],
        "hip_folders": ["/scenes/d/"],
        "texture_favorites": ["/tex/a/wood.png"],
        "geometry_favorites": ["/geo/c/rock.bgeo"],
        "hip_favorites": ["/scenes/d/shot.hip"],
        "texture_include_subfolders": False,
        "geometry_include_subfolders": True,
        "hip_include_subfolders": False,
    }

    def test_folders_union_in_order_without_duplicates(self):
        p = _prefs_with_settings(self, dict(self.OLD))
        self.assertEqual(
            ["/tex/a/", "/shared/b/", "/geo/c/", "/scenes/d/"],
            p.file_folders,
            "the union is not texture-then-geometry-then-hip with "
            "duplicates dropped")

    def test_favorites_union(self):
        p = _prefs_with_settings(self, dict(self.OLD))
        self.assertEqual(
            ["/tex/a/wood.png", "/geo/c/rock.bgeo", "/scenes/d/shot.hip"],
            p.file_favorites)

    def test_subfolders_seed_every_location_when_any_was_on(self):
        """One old section had recursion on, so every merged location
        starts recursive - recursion must not quietly turn off, and
        per-location is the shape it lands in now."""
        p = _prefs_with_settings(self, dict(self.OLD))
        self.assertEqual(sorted(p.file_folders),
                         sorted(p.file_recursive_folders))

    def test_the_old_keys_survive_the_save(self):
        """An older build on the other machine still reads and writes
        the old quartets - deleting them would split the fleet's
        settings forever (_LIST_KEYS unions name-for-name)."""
        p = _prefs_with_settings(self, dict(self.OLD))
        p.save()
        with open(os.path.join(p.path, "settings.json"),
                  encoding="utf-8") as handle:
            on_disk = json.load(handle)
        for key in ("texture_folders", "geometry_folders", "hip_folders",
                    "texture_favorites", "geometry_favorites",
                    "hip_favorites"):
            self.assertIn(key, on_disk, "%s was destroyed" % key)
        self.assertTrue(on_disk.get("file_section_migrated"),
                        "the marker did not persist - the union will "
                        "re-run and resurrect removed favourites")

    def test_the_migration_never_reruns(self):
        """A favourite removed AFTER the migration stays removed: the
        marker, not the content, decides."""
        p = _prefs_with_settings(self, dict(self.OLD))
        p.remove_file_favorite("/tex/a/wood.png")
        p.save()
        q = prefs_module.Prefs()
        q.path = p.path
        q.load()
        self.assertNotIn("/tex/a/wood.png", q.file_favorites,
                         "the migration re-ran and resurrected a "
                         "favourite the user removed")

    def test_the_file_tab_introduces_itself_once(self):
        old = dict(self.OLD)
        old["enabled_sections"] = ["material", "code"]
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
    """The locations and the File favourites move into the library
    (2026-08-05), and settings.json keeps the copy.

    Shaped on the REAL settings measured that day: fourteen registered
    locations, one custom name, one colour, one Show All Files override
    set to FALSE, twelve recursive, two favourites - and two locations
    carrying no decoration at all, which is the case the old
    `location_paths()` could not see because it was composed from the
    four decoration tables and registration was not one of them.
    """

    REAL_SHAPE = {
        "directory": "",
        "file_folders": ["/tex/img/", "/tex/bokeh/", "/photo/2023/",
                         "/models/obj/", "/houdini/exercise/", "/tex/hdr/"],
        "file_favorites": ["/tex/hdr/017.hdr", "/houdini/exercise/a.hiplc"],
        "file_folder_names": {"/tex/bokeh/": "Bokeh files"},
        "file_folder_colors": {"/photo/2023/": "#134d4d"},
        # FALSE, not absent: an override that turns Show All Files OFF
        # for one location. A normaliser that drops falsy fields would
        # silently turn it back on, and the real settings hold exactly
        # one of these.
        "file_folder_show_all": {"/models/obj/": False},
        "file_recursive_folders": ["/tex/img/", "/tex/bokeh/", "/photo/2023/",
                                   "/models/obj/"],
    }

    def _prefs(self, settings=None):
        library = tempfile.mkdtemp(prefix="amaze_loc_library_")
        self.addCleanup(shutil.rmtree, library, ignore_errors=True)
        data = dict(settings or self.REAL_SHAPE)
        # BEFORE load(), never after: load() ends by running the
        # migration, so a library assigned afterwards is assigned too
        # late and the real one has already been written to.
        data["directory"] = library
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        prefs = _prefs_with_settings(self, data)
        # load() normalises the library path to end in a separator, so
        # this compares the resolved form. It is an assertion and not a
        # comment because everything below writes real files: if the
        # redirect ever stops taking, these tests must stop rather than
        # run against whatever library the settings actually name.
        library = prefs.dir
        # normcase+normpath BOTH sides. `prefs.dir` comes back in the
        # HOUDINI spelling - forward slashes, trailing separator - while
        # tempfile.gettempdir() uses the platform's own, so on Windows
        # this compared 'C:/Users/.../Temp/...' against
        # 'C:\\Users\\...\\Temp' and was False for the separator alone.
        # It took all ten tests in this class down with it, each
        # reporting a fixture that was in fact pointed exactly where it
        # should be.
        self.assertTrue(
            os.path.normcase(os.path.normpath(library)).startswith(
                os.path.normcase(os.path.normpath(tempfile.gettempdir()))),
            "the fixture is pointed at %r" % (library,))
        return prefs, library

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
        """The case the four-table composition could not represent: two
        of the fourteen real locations carry nothing but registration."""
        prefs, _lib = self._prefs()
        self.assertEqual({"registered": True},
                         locations_mod.record(prefs, "/tex/hdr/"))
        self.assertIn("/houdini/exercise/", prefs.file_folders)

    def test_it_writes_the_two_files_and_marks_itself_done(self):
        prefs, library = self._prefs()
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

    def test_the_six_old_keys_are_still_written(self):
        """An older build on the other machine reads them, and they are
        the fallback copy. A3 and A4 are one mechanism."""
        prefs, _lib = self._prefs()
        prefs.save()
        with open(os.path.join(prefs.path, "settings.json"),
                  encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(6, len(on_disk["file_folders"]))
        self.assertEqual({"/tex/bokeh/": "Bokeh files"},
                         on_disk["file_folder_names"])
        self.assertEqual({"/models/obj/": False},
                         on_disk["file_folder_show_all"])
        self.assertEqual(sorted(self.REAL_SHAPE["file_recursive_folders"]),
                         sorted(on_disk["file_recursive_folders"]))
        self.assertEqual(6, len(on_disk["file_location_records"]))

    def test_the_second_mac_keeps_its_own_folders_and_gains_the_others(self):
        """THE SECOND MACHINE. Its settings.json is its OWN - preferences
        never synced between the two Macs (INSTALL.md), so its six keys
        are registered folders nothing has ever carried anywhere.

        The first version of this shipped taking the store as-is when it
        already held anything, on the reasoning that the six keys were a
        stale copy of a shared truth. They are not, and that machine's
        sidebar would have emptied on the first launch of this build,
        with the only record of what was lost being the file it had just
        replaced. Adopt-only, the engine's own rule.
        """
        first, library = self._prefs()          # the Mac that got there first
        self.assertEqual(6, len(first.file_folders))

        # A second machine, its own settings, the SAME library.
        second = _prefs_with_settings(self, {
            "directory": library,
            "file_folders": ["/laptop/only/", "/tex/img/"],
            "file_favorites": ["/laptop/only/shot.exr"],
            "file_folder_names": {"/laptop/only/": "Laptop scratch"},
        })
        # No explicit migrate(): load() runs it, which is the path that
        # actually happens on that machine. Asserting the END STATE, not
        # a second call's return value - the second call answers "done",
        # because by then it is.
        self.assertTrue(second.data.get(locations_mod.MIGRATED_KEY))
        self.assertIn("/laptop/only/", second.file_folders,
                      "the second machine's own registered folder was "
                      "discarded when it met a library that already had "
                      "locations in it")
        self.assertEqual(
            "Laptop scratch",
            locations_mod.record(second, "/laptop/only/").get("name"),
            "its label did not come with it")
        self.assertIn("/tex/bokeh/", second.file_folders,
                      "the first machine's folders did not arrive")
        self.assertIn("/laptop/only/shot.exr", second.file_favorites)
        self.assertIn("/tex/hdr/017.hdr", second.file_favorites)
        # /tex/img/ is registered on BOTH and must not double.
        self.assertEqual(
            1, list(second.file_folders).count("/tex/img/"),
            "a folder both machines had registered arrived twice")

    def test_a_lost_store_is_re_seeded_from_the_copy(self):
        """A `locations.json` deleted or restored away, on a machine that
        has already migrated, used to leave the sidebar EMPTY - the code
        trusted an empty store over its own copy and said nothing. It
        happened for real while section A was being built.
        """
        prefs, library = self._prefs()
        self.assertEqual(6, len(prefs.file_folders))

        os.remove(os.path.join(library, "locations.json"))
        locations_mod.forget()

        # The file is gone and the `.bak` tier proves it was here, so
        # the store answers BLIND and writes stay refused - that is
        # refuse-over-overwrite, not a fault. What must not happen is
        # the sidebar going empty with it.
        self.assertTrue(locations_mod.showing_last_known(prefs),
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
        """The other empty-store shape: a library pointed somewhere new,
        or replaced, so nothing says a store was ever here (FRESH). This
        machine still says it has migrated, so without the re-seed it
        would show an empty sidebar over a writable library forever."""
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
        """The other side of it, and the reason the copy is the right
        discriminator: `keep_last_known` writes the copy FROM the store,
        so removing the last location empties both and there is nothing
        to re-seed from. A rule that re-seeded on an empty store alone
        would make 'remove them all' impossible."""
        prefs, _library = self._prefs()
        for path in list(prefs.file_folders):
            prefs.remove_file_folder(path)
        locations_mod.forget()
        self.assertEqual([], list(prefs.file_folders),
                         "removing every location did not stick - they "
                         "came back from the copy")

    def test_a_migration_that_does_not_reproduce_refuses_to_mark(self):
        """The acceptance test is the END STATE, not that the write ran.

        A store whose normaliser cannot hold what went in must leave the
        marker unset, so the old keys stay the truth and the next launch
        tries again - the alternative is a library half-populated and a
        settings file that says the move is finished.
        """
        prefs, _lib = self._prefs({"file_folders": ["/a/"],
                                   "file_favorites": []})
        prefs.data[locations_mod.MIGRATED_KEY] = False
        locations_mod.forget()
        real_normalise = locations_mod.SPEC.normalise
        # A normaliser that quietly drops a field is exactly the failure
        # the comparison exists to catch (tile_icons.normalise really
        # does drop an icon this build does not ship).
        locations_mod.SPEC.normalise = lambda value: {}
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
        """DECIDED: the last known locations still list, marked
        unreachable. The File section is the browser you most want
        working when a drive is not mounted."""
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
        """The File section worked with no library configured, because
        it was backed by settings.json. It still has to: the answer to
        "where does this go" must not be a relative path beside the
        current directory, which is what an empty `dir` gives."""
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


class KindRouterTest(unittest.TestCase):
    """kind_for is the router every per-type behaviour hangs off, fed
    by the three sections' own recognisers - one source each."""

    def test_each_kind_routes_to_its_section_of_origin(self):
        for name, kind in (
                ("a.hip", "hip"), ("b.HIPLC", "hip"), ("c.hipnc", "hip"),
                ("d.png", "image"), ("e.EXR", "image"), ("f.hdr", "image"),
                # .rat is Houdini's own texture format - probed: sips
                # fails cleanly (exit 13, no file) so the pipeline's
                # iconvert fallback converts it like any EXR.
                ("m.rat", "image"),
                # Camera raw in the container macOS decodes natively -
                # probed 2026-08-07: sips converts a real DNG in ~2.3s.
                ("n.dng", "image"), ("o.DNG", "image"),
                ("g.bgeo.sc", "geometry"), ("h.obj", "geometry"),
                ("i.usd", "geometry"),
                ("j.txt", "other"), ("k.bvh", "other"), ("noext", "other"),
                ("l.hip.bak", "other")):
            self.assertEqual(kind, file_library.kind_for(name), name)


class ScenePathsAreSpelledPerPreferenceTest(unittest.TestCase):
    """Every path Amaze writes INTO THE SCENE goes through
    _scene_path - the function-sheet decision covered Copy Path and
    every path handed to the user after it, but the texture funnel,
    the geometry loader and the drag payload's text all wrote raw
    absolutes. Reported live 2026-08-07: Write Paths As on its
    default, absolute paths from every door."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def test_the_texture_funnel_writes_the_spelled_path(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_pathtest_tex")
        self.addCleanup(geo.destroy)
        loader = geo.createNode("file")
        self.panel._apply_texture_to_node(
            loader, home + "/textures/amaze_spelling.png")
        self.assertEqual(
            "$HOME/textures/amaze_spelling.png",
            loader.parm("file").rawValue(),
            "double-click and Load to Node write the raw absolute "
            "path, not the spelling Preferences asks for")

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
        """Live find: a file URL is an OS open-this handle. Houdini
        honoured it - a promoted drag released anywhere but a field
        offered to CLEAR THE SCENE and open the file, for every kind -
        and inside a field it beat the spelled text, which is why
        drops wrote absolute paths. One flavour only."""
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
    """The release-on-a-node verb: the node's FIRST file parameter
    takes the SPELLED path, and a node with no file parameter refuses
    with a False - dialog-free, so the gesture can show its own miss.
    Uniform across kinds; the dispatch is pinned in
    test_drag_gesture."""

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
        self.assertTrue(self.panel.drop_file_path_on_node(
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
            self.panel.drop_file_path_on_node(
                self._index_for(home + "/x.png"), bare),
            "a node with nothing to take the path claimed success")


class CreationRuleTest(unittest.TestCase):
    """The matrix's creation rule on real nodes: a release on empty
    network space (and a double-click with nothing selected) creates
    the payload's carrier - mtlximage, the MtlX colour ramp, the
    language's wrangle - wherever the network can hold one, and
    refuses with False where it cannot. Type names from the shipped
    manual; the type existing in the network's child category IS the
    capability test."""

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
        self.assertTrue(self.panel.create_image_node_in(
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
        self.assertFalse(self.panel.create_image_node_in(
            self._index_for(self._home() + "/x.png"), net))
        self.assertEqual((), net.children(),
                         "a refusing network gained a child anyway")

    def test_a_gradient_becomes_the_mtlx_ramp_carrier(self):
        from amaze.helpers import helpers

        net = self._matnet()
        index = self.panel.gradient_sorted_model.index(0, 0)
        self.assertTrue(index.isValid(),
                        "premise: the fixture has gradients")
        self.assertTrue(self.panel.create_gradient_node_in(index, net))
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
        self.assertTrue(self.panel.create_code_node_in(index, net))
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
        self.assertFalse(self.panel.create_code_node_in(index, net))
        self.assertEqual((), net.children())

    def _with_view_networks(self, networks):
        self.panel._view_create_networks = lambda: list(networks)
        self.addCleanup(
            lambda: self.panel.__dict__.pop("_view_create_networks", None))

    def test_a_positioned_carrier_never_auto_places(self):
        """Live find: the carrier ran moveToGoodPosition BEFORE taking
        its position - and that call may shove unconnected siblings
        aside to make room, which read as every other node moving
        away. A given position IS the placement; auto-place is only
        the no-position fallback."""
        from unittest import mock
        net = self._matnet()
        spot = hou.Vector2(-3.5, -2.25)
        with mock.patch.object(hou.Node, "moveToGoodPosition") as auto:
            ok = self.panel.create_image_node_in(
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
        """Live find: a release over a container node resolves INSIDE
        it while the cursor position stays in the OUTER editor's
        plane - stage coordinates applied inside a material library
        put the node anywhere but the cursor. The gated resolver
        answers only when the editor under the cursor is showing the
        destination network itself."""
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
        """Live find: created and imported nodes arrive SELECTED and
        current (Houdini tags them), so the editor scrolled to them
        and the NEXT double-click applied to the newborn and refused.
        A door leaves the artist's selection exactly as it was."""
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
        """The Materials menu's Copy To imports the selected asset into
        /mat - and the artist's scene selection must survive it,
        exactly as it survives a drop. The import tags its newborns
        current and selected; the verb's wrapper puts the artist
        back."""
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
        """Houdini answering no (a locked network) must not escape the
        click dispatcher as a slot crash - the drag dispatch already
        absorbs exactly this class and says why."""
        from amaze.panel import sections as sections_module

        class RefusingSection:
            key = "refusing"
            DROP = sections_module.DropRule(
                click_resolve="refuse_for_the_test")

        def refuse(_index):
            raise hou.PermissionError(
                "Cannot create a node inside a locked asset")

        self.panel.refuse_for_the_test = refuse
        index = self.panel.code_sorted_model.index(0, 0)
        try:
            self.panel.click_on_row(RefusingSection(), index)
        finally:
            del self.panel.refuse_for_the_test

    def test_a_genuine_crash_still_escapes_the_click_dispatcher(self):
        """Only the permission class is absorbed - a programming error
        must still crash where it can be seen."""
        from amaze.panel import sections as sections_module

        class CrashingSection:
            key = "crashing"
            DROP = sections_module.DropRule(
                click_resolve="crash_for_the_test")

        def crash(_index):
            raise RuntimeError("a real defect")

        self.panel.crash_for_the_test = crash
        index = self.panel.code_sorted_model.index(0, 0)
        try:
            with self.assertRaises(RuntimeError):
                self.panel.click_on_row(CrashingSection(), index)
        finally:
            del self.panel.crash_for_the_test

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
        """The outline draws the carrier the space door WOULD create,
        read from the same declaration the creator builds from. If the
        two could answer separately the ghost would be free to promise
        a wrangle and deliver nothing."""
        from amaze.panel import dragdrop_widgets, sections as sections_mod
        sop = self._geo()
        vop = self._matnet()
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        rule = sections_mod.SECTION_INDEX["code"].DROP
        self.panel._drag_index = index
        self.addCleanup(lambda: self.panel.__dict__.pop("_drag_index", None))
        promised = dragdrop_widgets.GridGestureMixin._ghost_type(
            self.panel, rule, "code", sop)
        self.assertTrue(self.panel.create_code_node_in(index, sop))
        made = [c for c in sop.children() if "wrangle" in c.type().name()]
        self.assertEqual(promised, made[0].type().name(),
                         "the ghost promised a different node than the "
                         "drop created")
        self.assertEqual(
            "", dragdrop_widgets.GridGestureMixin._ghost_type(
                self.panel, rule, "code", vop),
            "a network with no carrier still got a promise")

    def test_every_borrowed_overlay_is_given_back(self):
        """The overlay is ONE slot per editor: a ghost left behind is
        a shape stuck on the artist's network. Every exit path clears
        it - dragengine.end() runs on release, on cancel and on the
        leave the host treats as a suspend."""
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
        """Reported live: a material drop surfaced the editor at ROOT
        with `mat` boxed. An import tags its nodes current
        (`hou.moveNodesTo`, incidental - research.md), and an unpinned
        editor is in the FollowSelection link group, so it DIVES.
        Restoring the current node alone does not undo the dive: the
        editor's PWD is remembered and restored too."""
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
        """Selection calls push `Change Selection` entries
        (research.md ▸ Viewport & picking), so restoring the artist's
        selection would spray undo steps on EVERY drop. The whole
        restore runs under hou.undos.disabler()."""
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
        """Reported live: a geo network open, a SPHERE selected (in
        Houdini something almost always is), a VEX snippet
        double-clicked - and the one refusal sentence. The door aimed
        at the selection, the sphere has no snippet parm, and it
        refused instead of creating in the visible network.
        The selection is a HINT for the click door, not a veto."""
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
        """The audit's finding, as a pair. The test above proves the
        DOUBLE-CLICK treats a useless selection as a hint; the menu
        entry beside it, labelled with the same verb, called a
        refusal directly and created nothing.

        Same tile, same selection, two answers - and the click door's
        own docstring records that the veto was the bug it was written
        to remove. Driven through `menu_apply`, the thing the menu
        table actually names, so it fails if the routing regresses no
        matter how the body is spelled."""
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
        """The accept path. Falling through must not become "always
        create": a selected node that takes the snippet still takes
        it, and no carrier is made beside it."""
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
        """The live case, corrected by the probe: a SOP Create is a
        LOCKED HDA - Houdini refuses creation in it and in its sopnet
        - and the `create` subnet inside is the one node the asset
        MARKS editable, where creation succeeds. The walk must skip
        the locked levels (saying why in the log) and land in the
        editable one, never unlock the asset."""
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
        # The locked levels first, then the editable one - the walk
        # sees all three and only the last can take the carrier.
        self._with_view_networks([sc, sc.node("sopnet"), editable])
        hou.clearAllSelected()
        before = len(editable.children())
        self.panel.click_on_row(section, index)
        self.assertEqual(before + 1, len(editable.children()),
                         "the walk did not reach the editable subnet")
        self.assertTrue(sc.isLockedHDA(),
                        "the asset was UNLOCKED to make room - never")

    def test_a_geo_double_click_fills_the_selected_node(self):
        """Live find: the file door's geo branch imported no matter
        what was selected. The matrix aims a double-click at the
        selection first - a selected node with a file parameter takes
        the spelled path, exactly as the image branch beside it."""
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
        """Live find: an import leaves its nodes SELECTED (Houdini
        tags moved nodes), so the next double-click read a selection
        the user could not see, applied to it, and refused - every
        time, in every section. The door considers only selection
        inside the visible editors' networks."""
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
        """The live find: a code double-click with a material editor
        listed first must still land its wrangle in the geometry
        network - ONE resolver walks the visible networks and the
        first that can hold the carrier wins. Reported live: the drag
        created the wrangle and the double-click refused, because the
        two doors resolved the network with two different heads."""
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
        self.assertTrue(self.panel.create_image_node_in(
            self._index_for(home + "/textures/amaze_pos.png"), net,
            spot))
        children = net.children()
        self.assertEqual(1, len(children))
        # The BODY centres on the release point, so the anchor sits a
        # half-size short of it - the host's own new-node convention
        # (helpers.centred_on says why).
        from amaze.helpers import helpers
        anchor = helpers.centred_on(spot)
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
        """Removed 2026-08-01 on request: "Auto (most specific)"
        explained nothing. Fails if the option or its machinery
        returns; a machine that STORED "auto" lands on the default
        instead of a dead token."""
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
        """Preferences > Library carries a Test Library switch and a
        Test Folder row. While it is on, the Library Path and Cache
        Path rows are INERT: they show where the library actually
        points, and their browse buttons would otherwise write the
        real fields with a test path - the one combination that could
        lose a library.
        """
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

        self.assertEqual(os.path.join(folder, "lib") + "/", p.dir)
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
        """Preferences > Library > Cache Path carries a Default beside
        the browse button. It CLEARS the preference rather than
        writing today's default as a literal path, so the cache keeps
        following this machine's own convention.
        """
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

    def test_the_version_author_field_shows_a_real_name(self):
        """Preferences > Library shows the name this machine signs
        versions with. A fresh prefs gets its colour name minted
        RIGHT THERE and shown - the box never promises a mystery
        pick. Typing a name of your own persists it."""
        from amaze.core import versions
        from amaze.dialogs import prefs_dialog
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        shown = dlg.line_version_author.text()
        self.assertIn(shown, versions.PLACEHOLDER_NAMES,
                      "a fresh prefs must show the minted colour "
                      "name, not a blank")
        self.assertEqual(shown, p.version_author,
                         "the shown name must be the persisted one")
        dlg.line_version_author.setText("  MyOwnName  ")
        dlg._save_version_author()
        self.assertEqual("MyOwnName", p.version_author,
                         "typed name (trimmed) did not reach prefs")

    def test_the_default_style_pins_home(self):
        """Preferences > Write Paths As defaults to $HOME (the
        decided default): a path under $HIP still says $HOME/...
        unless the user chooses otherwise."""
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
    """Only what FileFiles reads - over the REAL location store.

    The locations and the favourites moved into the library on
    2026-08-05, so `file_folders` and the four decoration tables are
    derived, not held. A stub that keeps carrying them as plain
    attributes still ACCEPTS every write and answers none of them: the
    tests would pass their own values back to themselves while the code
    under test read an empty store. It owns a private library directory,
    so every one of those surfaces resolves the way it does in
    production.
    """

    def __init__(self, folders=()):
        self.dir = tempfile.mkdtemp(prefix="amaze_file_lib_")
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

    # -- the last-known copy, as Prefs holds it ------------------------

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

    # -- the same delegating surface Prefs carries ---------------------

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
        locations_mod.set_record(self, old, {})
        locations_mod.set_record(self, new, record)
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
    """file_key is the identity everything keyed about a file hangs on -
    its comment, its icon override, the drag bookkeeping - so the same
    file must produce the SAME key however its location was spelled.

    The detour registration below is not exotic: registered folders are
    stored `$AMAZE`-relative, `hou.text.expandString` substitutes
    verbatim and collapses nothing (measured 2026-08-06), so every real
    key on both platforms carried `../../..` from the location's
    spelling - and on Windows, mixed separators on top. One location
    re-registered absolute would have orphaned every key made under the
    relative spelling."""

    def _model_over(self, folder):
        from amaze.helpers import hostos  # noqa: F401 - guard below
        model = file_library.FileFiles(_Prefs([folder]))
        model.set_folder(folder)
        return model

    def test_the_key_is_one_canonical_spelling(self):
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.mkdir(os.path.join(tmp, "sub"))
        with open(os.path.join(tmp, "a.png"), "w") as handle:
            handle.write("x")
        from amaze.helpers import hostos
        detour = os.path.join(tmp, "sub", os.pardir)
        model = self._model_over(detour)
        self.assertGreater(model.rowCount(), 0, "the fixture scanned "
                                                "nothing - this test is "
                                                "not testing keys")
        for row in range(model.rowCount()):
            key = model.file_key(row)
            self.assertEqual(
                hostos.canonical_path_key(key), key,
                "file_key %r is not canonical - the same file reached "
                "through a differently-spelled location gets a different "
                "identity, and its comment and icon are keyed to the "
                "spelling" % key)
            self.assertTrue(
                os.path.isfile(key),
                "the canonical key %r no longer opens as a path" % key)

    def test_an_out_of_range_row_stays_empty(self):
        """normpath("") is "." (research.md > empty path), so a blind
        canonicalise would turn the no-such-row answer into a truthy,
        real-looking relative path every `if not key` guard misses."""
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        model = self._model_over(tmp)
        self.assertEqual("", model.file_key(999))
        self.assertEqual("", model.file_key(-1))


class OsIconTest(unittest.TestCase):
    """A file Amaze does not recognise still gets a picture: the OS's
    own icon, drawn on a transparent tile-sized canvas, never scaled
    past 2x its native size (the recorded probe's caveat)."""

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
    """A stand-in `self` for the live click door - click_on_row and
    _apply_click_rule run for real, and the door verbs the drop table
    names record instead of touching a scene."""

    file_files_model = file_library.FileFiles

    def __init__(self):
        self.calls = []
        self.prefs = _Prefs([])

    def _visible_selected_nodes(self):
        """Nothing selected - the dispatch test drives the per-kind
        routing, not the selection door."""
        return []

    def _view_create_networks(self):
        """One writable network, so the on-space route can land."""
        return [object()]

    def _cannot_load_here(self):
        self.calls.append("refused")

    def create_image_node_in(self, index, network):
        self.calls.append("create_image_node_in")
        return True

    def click_import_geo(self, index):
        self.calls.append("click_import_geo")
        return True

    def click_open_hip(self, index):
        self.calls.append("click_open_hip")
        return True

    def click_copy_path(self, index):
        self.calls.append("click_copy_path")
        return True


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
    """Each kind reaches its own verb THROUGH THE LIVE DOOR - the
    drop table plus click_on_row's precedence, nothing selected, so
    the no-node route decides. The per-kind panel handler this class
    asserted before (`file_double_click`) is retired: production
    routes through the table, and the handler had drifted into
    refusals the table never makes. Breaks when a DROP_BY_KIND row
    loses its verb, names a different one, or the door's precedence
    stops reaching the no-node route."""

    def test_every_kind_reaches_its_own_verb(self):
        from amaze.panel import panel as panel_mod
        from amaze.panel import sections
        for kind, expected in (("image", "create_image_node_in"),
                               ("geometry", "click_import_geo"),
                               ("hip", "click_open_hip"),
                               ("other", "click_copy_path"),
                               ("", "click_copy_path")):
            recorder = _RecordingPanel()
            recorder._apply_click_rule = (
                panel_mod.MatLibPanel._apply_click_rule.__get__(recorder))
            panel_mod.MatLibPanel.click_on_row(
                recorder, sections.FileSection, _FakeIndex(kind))
            self.assertEqual([expected], recorder.calls,
                             "kind %r dispatched %r" % (kind,
                                                        recorder.calls))


class CopyPathTest(unittest.TestCase):
    """Copy Path fills the clipboard with HOUDINI paths, one per line,
    and no dialog."""

    def test_paths_land_houdini_shaped_one_per_line(self):
        from amaze.panel import panel as panel_mod
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        recorder = _RecordingPanel()
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
    """The sheet: a hip dragged OUTSIDE Amaze does what double-click
    does - loads the scene. Released inside the panel it stays silent,
    because a drag that ends where it began is not a decision."""

    def _armed_hip(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_drag_gesture as harness_mod
        h = harness_mod._Harness(self, "file", kind="hip")
        h.panel.open_hip_scene = (
            lambda idx: h.panel.calls.append("open"))
        h.press()
        h.view._dragging = True
        h.view._drag_panel = h.panel
        return h

    def _release_at_global(self, h, global_point):
        """The inside/outside decision reads event.globalPosition(),
        and a locally-constructed QMouseEvent defaults that to the REAL
        cursor - so the test must say the global point explicitly."""
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
    """Tooltips cap at 800 REAL screen pixels and wrap (two live-pass
    reports: a plain-text tooltip renders as ONE line however long,
    and a logical-px cap doubles on a Retina screen)."""

    def _with_dpr(self, dpr):
        """Pin the screen ratio the cap divides by, restored after."""
        from amaze.helpers import ui_helpers
        original = ui_helpers._screen_dpr
        ui_helpers._screen_dpr = lambda: dpr
        self.addCleanup(setattr, ui_helpers, "_screen_dpr", original)

    def test_a_short_tooltip_passes_through_untouched(self):
        from amaze.helpers import ui_helpers
        self.assertEqual("Short and sweet",
                         ui_helpers.tooltip_text("Short and sweet"))

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
        """The live report, replayed: on a 2x screen the Show Unknown
        Files sentence measured ~720 LOGICAL px - under a logical cap
        of 800, so it drew plain, one line, ~1450 real pixels wide.
        In real pixels the cap is 400 logical there, and it wraps."""
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
    """The unified badge family renders the favourite star AS DRAWN,
    so a star-colour preference had nothing left to colour - the two
    rows left the dialog (the 2026-08-01 call), the keys left the
    store, and the notes accent pinned to the theme's star token."""

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
        """An existing settings.json still carries the retired keys,
        and save()'s unknown-key courtesy (which rightly KEEPS a newer
        build's keys) would re-adopt them from disk on every write -
        the exact hole _RETIRED_KEYS closes. Both behaviours in one
        file: the retired keys drop, the future key survives."""
        import json
        p = test_support.fixture_prefs(self)
        p.save()
        final = p.path + "/settings.json"
        with open(final, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["star_color_mode"] = "custom"
        raw["star_custom_color"] = "#123456"
        raw["key_from_a_newer_build"] = "kept"
        with open(final, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=4)
        p.save()
        with open(final, encoding="utf-8") as handle:
            after = json.load(handle)
        for gone in ("star_color_mode", "star_custom_color"):
            self.assertNotIn(
                gone, after,
                "a retired key rode the unknown-key courtesy back "
                "into settings.json - it will now live there forever")
        self.assertEqual(
            "kept", after.get("key_from_a_newer_build"),
            "the courtesy for a NEWER build's keys broke - retirement "
            "must name its keys, not drop everything unknown")


class PrefsComboFocusTest(unittest.TestCase):
    """Every Preferences dropdown refuses focus. Houdini's stylesheet
    paints a focused combo navy with a blue ring, so a focusable combo
    ends up permanently singled out - whichever one was last clicked.
    The dialog has a NoFocus sweep for this; it ran BEFORE the tab
    widget joined the dialog's tree, matched nothing, and fixed
    nothing (live report 2026-07-31, the Write Paths As ring)."""

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
        """Source-derived: a bare multi-line setToolTip is the exact
        shape that regresses into the screen-wide bar."""
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
    """The four confirmed location asks (2026-07-31): removal sweeps
    the folder's cached thumbnails, recursion is per location, the
    default name is the path itself (Houdini-collapsed), and a
    location can be renamed - with Locate carrying both along."""

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

    def test_the_default_name_is_the_houdini_path(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        target = home + "/amaze_loc_naming/"
        model, _prefs = self._folders_model(target)
        label = model.data(model.index(1, 0),
                           QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual("$HOME/amaze_loc_naming", label,
                         "the default label is not the path: %r" % label)

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
        # Canonical, the locations API's spelling since the
        # portable-spelling change.
        new_key = hostos.canonical_path_key(new) + "/"
        self.assertEqual({new_key: "Set Dressing"},
                         prefs.file_folder_names,
                         "the custom name did not follow the move")
        self.assertEqual([new_key], prefs.file_recursive_folders,
                         "the recursion flag did not follow the move")

    def test_locate_moves_the_pointer_and_the_favourites(self):
        """The two writes Locate makes that nothing else asserts.

        The registered pointer moves IN ITS OWN ROW - relocating the
        second of two locations must not reorder the sidebar - and every
        favourite under the old path is rewritten onto the new one.

        Both were index assignments into a live prefs list, so anything
        that stops `file_folders`/`file_favorites` being that same list
        turns them into silent no-ops: a Locate that reports success,
        logs a favourite count and moves nothing. Neither raises, so
        only an assertion on the END STATE can see it.
        """
        first = self._tmpdir()
        old = self._tmpdir()
        new = self._tmpdir()
        old_key = old if old.endswith("/") else old + "/"
        # A REAL Prefs, not the read-only stub: this pins
        # `relocate_file_folder` and the favourites list as they
        # actually ship. A stub carrying its own copy of the move would
        # verify the copy (practice.md ▸ *A test that re-derives the
        # logic*), which is worth nothing when the point is that the
        # production write must not silently stop landing.
        prefs = _prefs_with_settings(self, {
            "file_folders": [first, old],
            "file_favorites": [old_key + "keep.exr", "/elsewhere/other.exr"],
        })
        prefs.dir = self._tmpdir(prefix="amaze_loc_lib_")
        model = file_library.FileFolders(prefs)

        rewritten = model.relocate_folder(2, new)

        # Canonical on both sides - the API's spelling now.
        new_key = hostos.canonical_path_key(new) + "/"
        first = hostos.canonical_path_key(first)
        self.assertEqual(1, rewritten,
                         "Locate did not report the favourite it moved")
        self.assertEqual([first, new_key], list(prefs.file_folders),
                         "the registered pointer did not move, or the row "
                         "changed position")
        # Sorted, not in insertion order: the favourites are a keyed
        # store now and their order is the file's, not the user's -
        # nothing reads this list except as a membership test.
        self.assertEqual(sorted(["/elsewhere/other.exr",
                                 new_key + "keep.exr"]),
                         sorted(prefs.file_favorites),
                         "a favourite under the moved location was left "
                         "pointing at the old path")

    def test_removal_sweeps_the_cache_but_not_captures(self):
        """The confirmed decision, end to end against a real cache
        layout: the removed folder's thumbnails go, a file another
        location still covers stays, an unreadable manifest is left
        alone, and the hip capture store is never touched."""
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

        # An unreadable sibling manifest must be left alone entirely.
        bad_dir = os.path.join(cache_root, "geo_thumbnails_bad_black_256")
        os.makedirs(bad_dir, exist_ok=True)
        with open(os.path.join(bad_dir, "manifest.json"), "w") as f:
            f.write("{corrupt")
        self.addCleanup(shutil.rmtree, bad_dir, ignore_errors=True)

        # A capture store with content that must survive.
        from amaze.core import scene_captures
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
        """ALL FOUR surfaces, and this asserts the OUTCOME rather than
        which setter ran.

        It used to spy on `set_file_folder_name` and
        `set_file_folder_recursive` - the two the removal happened to
        call - so it could not see that the COLOUR and the Show All
        Files override were never cleared at all. A test written
        against the mechanism cannot notice the mechanism is two short;
        this one reads the four surfaces afterwards."""
        tmp = self._tmpdir()
        # TWO locations, and the assertions below read the SURVIVOR.
        # With one, "the removed location's record was retired" and
        # "every location's record was wiped" are the same observation -
        # proved 2026-08-03 by replacing the retire call with four
        # blanket .clear() calls and watching all 50 tests stay green.
        kept = self._tmpdir()
        model, prefs = self._folders_model(tmp, kept)
        for path, name, colour, show, in ((tmp, "Custom", "#ff8000", True),
                                          (kept, "Kept", "#0080ff", False)):
            prefs.set_file_folder_name(path, name)
            prefs.set_file_folder_color(path, colour)
            prefs.set_file_folder_show_all(path, show)
            prefs.set_file_folder_recursive(path, True)
        prefs.save = lambda: None
        # remove_folder mutates prefs.file_folders via the prefs
        # method on the real Prefs; the stub needs it.
        prefs.remove_file_folder = (
            lambda path: prefs.file_folders.remove(path))
        from unittest import mock
        with mock.patch.object(
                file_library, "sweep_folder_cache") as sweep:
            model.remove_folder(1)
        # Canonical, the API's spelling since the portable-spelling
        # change; `kept` and `tmp` were made natively by mkdtemp.
        kept = hostos.canonical_path_key(kept)
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
    """Clean Library drops dead location pointers - and it has to do it
    through the MODEL (2026-08-05).

    `FolderListModel` reads its rows straight out of prefs, holding no
    copy, so writing to prefs changes the row COUNT with nothing
    announcing it. Cleanup used to do exactly that and then emit a
    bare `layoutChanged`, which is the wrong signal for a changed
    count (`category.normalize_categories` says why) AND a native H21
    segfault (research.md ▸ *A BARE layoutChanged.emit() SEGFAULTS
    H21 TOO*). `remove_folder` wraps the same prefs write in
    `beginRemoveRows`.

    THREE locations with a live one BETWEEN the two dead ones, because
    that is the setup a wrong one fails on: removing low-row-first
    shifts every row above it, so the second removal aims at a row
    that no longer exists and the second dead pointer survives. With
    one dead location the two orders are indistinguishable.
    """

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
        # The locations API answers CANONICAL absolutes since the
        # portable-spelling change; the fixture's native tmp spelling
        # is converted on the way in, so the expectation converts too.
        self.assertIn(
            hostos.canonical_path_key(alive), survivors,
            "cleanup removed a location whose folder is still there")
        for path in (dead_a, dead_b):
            self.assertNotIn(
                hostos.canonical_path_key(path), survivors,
                "a dead location survived cleanup - the second removal "
                "aimed at a row the first one had already shifted")


class ShowUnknownFilesSwitchTest(unittest.TestCase):
    """Preferences > Show Unknown Files. ON (the default) is the
    merge's behaviour - a folder shows what is in it. OFF restores the
    pre-merge view: only kinds Amaze can thumbnail, and the sidebar
    count agrees with the grid in BOTH states (the review lesson)."""

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
    """The adversarial review round on the merge diff (2026-07-31):
    five confirmed defects, one pin each."""

    def test_prefs_close_does_not_refresh_from_another_section(self):
        """THE HIGH FINDING. _prefs_dialog_closed refreshed the merged
        model unconditionally, and the merged model's refresh can start
        the BLOCKING geometry render pass - so Delete Local Cache from
        the Material tab froze Houdini rendering geometry nobody was
        looking at. The refresh must be gated on the File section
        actually showing; the next File activation rescans anyway."""
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

        # Drive ONLY the gated tail of the real method: everything
        # before it needs a constructed panel, so the pin is the gate
        # itself, source-checked to sit in _prefs_dialog_closed.
        import inspect
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
        """The sidebar counted subdirectories (matches() sees only
        names); the grid lists files. 3 files + 2 subfolders must read
        3, not 5."""
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
        """The skip-hidden rule applied to files but not directories,
        so Include Subfolders on a project folder flooded the grid
        with .git internals - and the count with them."""
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
        """The Show/Hide rebuild dropped every key not in this build's
        registry - deleting the OTHER machine's (older build's) tabs
        by side effect, the recorded toggle-deleted-HIP shape again."""
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
        """Two rows, one physical file, one key: the total must be 1
        (a row-count total leaves the bar short forever and the
        manifest flush never fires), and the freshly built key must
        land in _key_rows or its delivery repaints nothing and the
        disk cache is never written."""
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
            # `flush` too: rerender_thumbnails passes flush=False and
            # writes the manifest ONCE after the loop, where it used to
            # serialise the whole thing per row.
            cache.return_value.invalidate = lambda full, flush=True: None
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
    """Locations carry colours like categories do (2026-07-31). The
    sidebar answers the SAME role the asset sidebars answer, so one
    delegate paints both; the tile reads the colour of the location
    its file came from."""

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
        """One delegate reads ONE number for every section, so File and
        Colors must agree with Material's UserRole + 8. Asserted
        against the literal AND against each other: MaterialLibrary
        sets its role in __init__, so a class-level hasattr on it is
        False and a "compare to Material" check quietly compares
        FileFiles to itself."""
        from PySide6 import QtCore as _Qt
        from amaze.core import gradient_library as grad_mod
        expected = int(_Qt.Qt.ItemDataRole.UserRole) + 8
        self.assertEqual(expected,
                         int(file_library.FileFiles.CategoryColorRole))
        self.assertEqual(expected,
                         int(grad_mod.GradientLibrary.CategoryColorRole))


class ShowAllFilesTest(unittest.TestCase):
    """The per-location Show All Files override (2026-08-01): one
    location can show its unknown files while the global preference
    hides them - and the sidebar count agrees with the grid either
    way, per location."""

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


if __name__ == "__main__":
    unittest.main()
