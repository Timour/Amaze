"""Prefs, online sources, and the long tail - several of these read the SOURCE, and by AST rather than by text."""

import ast
import contextlib
import ntpath
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import file_library, renderers  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_of(relative):
    with open(os.path.join(PACKAGE, relative), encoding="utf-8") as handle:
        return handle.read()


def calls(relative, func_name, callee) -> bool:
    """Does `func_name` CALL `callee`? By AST, never by text - prose naming a helper is not a call to it."""
    tree = ast.parse(source_of(relative))
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func_name):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "attr", getattr(call.func, "id", ""))
            if name == callee:
                return True
    return False


class TheRendererTableIsWrittenOnce(unittest.TestCase):
    """ONE renderer table, `core/renderers.py`: every preference, switch and menu reads it."""

    def test_each_renderer_has_its_preferences(self):
        self.assertTrue(renderers.ALL, "the renderer table is empty")
        for renderer in renderers.ALL:
            for attr in (renderer.switch, renderer.samples):
                with self.subTest(renderer=renderer.key, attr=attr):
                    self.assertTrue(hasattr(prefs_mod.Prefs, attr),
                                    "%s names no preference %s" % (renderer.key, attr))

    def test_every_renderer_can_be_switched_on_by_saving_one(self):
        """A first save of a renderer switched off would be invisible in the tab it came from."""
        class Panel:
            prefs = prefs_mod.Prefs()

            def save(self):
                pass

        from amaze.panel import panel as panel_mod
        fake = Panel()
        fake.prefs.save = lambda: None
        for renderer in renderers.ALL:
            setattr(fake.prefs, renderer.switch, False)
        for renderer in renderers.ALL:
            for stored in (renderer.key,) + renderer.aliases:
                with self.subTest(stored=stored):
                    setattr(fake.prefs, renderer.switch, False)
                    panel_mod.AmazePanel.enable_renderer_on_add(fake, stored)
                    self.assertTrue(getattr(fake.prefs, renderer.switch),
                                    "saving a %s material did not switch it on" % stored)

    def test_no_other_module_spells_a_renderer_preference(self):
        """A switch or sample count named outside the table is a second home for a renderer."""
        spelled = []
        for root, _dirs, files in os.walk(PACKAGE):
            if os.sep + "tests" in root:
                continue
            for name in files:
                path = os.path.join(root, name)
                if not name.endswith(".py") or path.endswith(os.path.join("core", "renderers.py")):
                    continue
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                for renderer in renderers.ALL:
                    for attr in (renderer.switch, renderer.switch_stored, renderer.icon):
                        if '"%s"' % attr in source or "'%s'" % attr in source:
                            spelled.append("%s: %s" % (os.path.relpath(path, PACKAGE), attr))
        self.assertEqual([], spelled, "a renderer fact is spelled outside core/renderers.py")


class RendererDefaultsAgree(unittest.TestCase):

    def test_an_empty_directory_loads_the_documented_defaults(self):
        """load() returns before its `.get()` defaults on a machine with no settings file, so __init__'s values are what that machine keeps."""
        empty = tempfile.mkdtemp(prefix="amaze_prefs_defaults_")
        self.addCleanup(shutil.rmtree, empty, True)
        p = prefs_mod.Prefs()
        p.path = empty
        p.load()
        from amaze.prefs import persistence
        for attr, default in persistence.RENDERER_DEFAULTS.items():
            self.assertEqual(
                default, getattr(p, attr.lstrip("_")),
                "%s does not match the documented default on a machine "
                "with no settings file - which is what a new machine "
                "is, and closing Preferences then writes it out "
                "permanently" % attr)

    def test_the_filter_menu_offers_renderers_on_a_new_machine(self):
        """The user-visible half: all-off left the Materials Filter menu offering `All` over a library full of renderers."""
        empty = tempfile.mkdtemp(prefix="amaze_prefs_menu_")
        self.addCleanup(shutil.rmtree, empty, True)
        p = prefs_mod.Prefs()
        p.path = empty
        p.load()
        offered = [renderer.key for renderer in renderers.offered(p)]
        self.assertIn("Karma", offered)
        self.assertIn("Redshift", offered)


class SharedDefaultsLiveInOneTable(unittest.TestCase):
    """`SHARED_KEYS` states each shared default once; `__init__` and `load()` both read it."""

    def _settings(self, document):
        import json
        folder = tempfile.mkdtemp(prefix="amaze_shared_defaults_")
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(document, handle)
        return folder

    def test_a_fresh_prefs_holds_every_table_default(self):
        from amaze.prefs import persistence
        p = prefs_mod.Prefs()
        for stored, (_prop, attr, default) in \
                persistence.SHARED_KEYS.items():
            self.assertEqual(default, getattr(p, attr),
                             "%s: __init__ disagrees with the table" % stored)

    def test_load_falls_back_to_every_table_default(self):
        from amaze.prefs import persistence
        p = prefs_mod.Prefs()
        p.path = self._settings({"library_user": ""})
        for _prop, attr, _default in persistence.SHARED_KEYS.values():
            setattr(p, attr, "left over")
        p.load()
        for stored, (_prop, attr, default) in \
                persistence.SHARED_KEYS.items():
            self.assertEqual(default, getattr(p, attr),
                             "%s: load() kept a value the file never "
                             "held" % stored)

    def test_load_takes_only_a_string_for_the_folder_layout(self):
        """The adopt refused a non-string for these; load() took it, and paths were built from it."""
        p = prefs_mod.Prefs()
        p.path = self._settings(
            {"shared_settings": {"img_dir": 5, "extension": None}})
        p.load()
        self.assertEqual(("img/", ".mat"), (p.img_dir, p.ext),
                         "a junk folder-layout value loaded raw")

    def test_a_library_folder_saved_without_its_slash_loads_with_it(self):
        """A folder without its slash glued onto file names: `librarylibrary.json`."""
        library = tempfile.mkdtemp(prefix="amaze_no_slash_").replace("\\", "/")
        self.addCleanup(shutil.rmtree, library, True)
        p = prefs_mod.Prefs()
        p.path = self._settings({"directory": library.rstrip("/")})
        p.load()
        self.assertEqual(library.rstrip("/") + "/library.json", p.dir + "library.json")

    def test_load_clamps_parallel_downloads_as_the_adopt_does(self):
        p = prefs_mod.Prefs()
        p.path = self._settings(
            {"shared_settings": {"matx_parallel_downloads": 64}})
        p.load()
        self.assertEqual(16, p.matx_parallel_downloads,
                         "load() skipped the setter's 1-16 clamp")


class LoadNeverRaisesAndAlwaysValidates(unittest.TestCase):

    POISON = {  # every key with a validating setter, against the value that breaks it; `null` is the shape a hand edit or a future build's type change produces
        "scroll_speed": None,
        "ram_cache_mb": None,
        "texture_parallel_conversions": "eight",
        "karma_rendersamples": None,
        "octane_rendersamples": "many",
        "view_mode": None,
        "accent_color": None,
        "rendersize": None,
        "rendersamples": "lots",
        "render_on_import": None,
    }

    def _write_poison(self, folder, **extra):
        import json
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(dict(self.POISON, **extra), handle)

    def test_a_poisoned_settings_file_still_loads(self):
        folder = tempfile.mkdtemp(prefix="amaze_prefs_poison_")
        self.addCleanup(shutil.rmtree, folder, True)
        self._write_poison(folder)

        p = prefs_mod.Prefs()
        p.path = folder
        p.load()          # must not raise: panel._build re-raises

        self.assertIsInstance(p.scroll_speed, float)  # and USABLE: Preferences does arithmetic on these inside a slot where PySide swallows the error
        round(p.scroll_speed * 100)
        self.assertIsInstance(p.ram_cache_mb, int)
        self.assertIsInstance(p.texture_parallel_conversions, int)
        self.assertIsInstance(p.karma_rendersamples, int)
        self.assertEqual(256, p.octane_rendersamples)
        self.assertIn(p.view_mode, ("grid", "list"))
        self.assertTrue(p.accent_color)
        self.assertEqual((256, 256, 1), (p.rendersize, p.rendersamples,
                                         p.render_on_import),
                         "a junk render setting loaded raw instead of "
                         "falling back to its default")

    def test_preferences_opens_over_a_poisoned_file(self):
        """The Render rows hand these straight to spin boxes, which raise on anything but a number."""
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        self._write_poison(p.path, directory=p.dir,
                           library_user=test_support.FIXTURE_USER)
        p.load()
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(256, dlg.line_rendersize.value())
        self.assertEqual(256, dlg._samples_spins["Redshift"].value())
        self.assertTrue(dlg.cbx_render_on_import.isChecked())

    def test_the_render_setters_cast_and_clamp_to_the_rows_ranges(self):
        p = prefs_mod.Prefs()
        for name, given, kept in (("rendersize", "512", 512),
                                  ("rendersize", 99999, 1024),
                                  ("rendersize", 8, 64),
                                  ("rendersamples", 0, 1),
                                  ("rendersamples", 4096.0, 1024),
                                  ("render_on_import", "0", 0),
                                  ("render_on_import", 7, 1)):
            with self.subTest(setting=name, value=given):
                setattr(p, name, given)
                self.assertEqual(kept, getattr(p, name))
        for name in ("rendersize", "rendersamples", "render_on_import"):
            with self.subTest(setting=name, value=None):
                with self.assertRaises((TypeError, ValueError)):
                    setattr(p, name, None)    # a raise is how a junk value reaches its default

    def test_every_spin_row_offers_what_its_setter_keeps(self):
        """A value past a row's end is kept at that end, so the row can always show what is stored."""
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        for row, name, scale in (
                (dlg.line_rendersize, "rendersize", 1),
                (dlg._samples_spins["Redshift"], "rendersamples", 1),
                (dlg._samples_spins["Karma"], "karma_rendersamples", 1),
                (dlg._samples_spins["Octane"], "octane_rendersamples", 1),
                (dlg.spin_ram_cache, "ram_cache_mb", 1),
                (dlg.spin_parallel, "texture_parallel_conversions", 1),
                (dlg.spin_matx_parallel, "matx_parallel_downloads", 1),
                (dlg.spin_scroll_speed, "scroll_speed", 100)):
            for end, past in ((row.minimum(), row.minimum() - 1),
                              (row.maximum(), row.maximum() + 1)):
                with self.subTest(setting=name, value=past):
                    setattr(p, name, past if scale == 1 else past / scale)
                    self.assertEqual(end, round(getattr(p, name) * scale),
                                     "the setter keeps a value its row "
                                     "cannot show")

    def test_a_hidden_renderer_has_no_samples_row(self):
        """Its Show/Hide switch hides the Render tab's row, and brings it back."""
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        for renderer in renderers.ALL:
            setattr(p, renderer.switch, renderer is not renderers.OCTANE)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        form, row = dlg._samples_rows[renderers.OCTANE.key]
        self.assertFalse(form.isRowVisible(row), "a hidden renderer kept its samples row")
        for renderer in (renderers.KARMA, renderers.REDSHIFT):
            shown_form, shown_row = dlg._samples_rows[renderer.key]
            self.assertTrue(shown_form.isRowVisible(shown_row))
        dlg._renderer_boxes[renderers.OCTANE.switch].setChecked(True)
        self.assertTrue(form.isRowVisible(row), "switching it on did not bring the row back")
        self.assertTrue(p.renderer_octane_enabled)


class ThePerUserBlocksRoundTripAndMerge(unittest.TestCase):
    """The users dimension of settings.json: per-UID blocks, and the merge two panes of one session put them through."""

    def _prefs_at(self, folder):
        p = prefs_mod.Prefs()
        p.path = folder
        return p

    def _folder(self):
        folder = tempfile.mkdtemp(prefix="amaze_users_dim_")
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def _write(self, folder, document):
        import json
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(document, handle)

    def _read(self, folder):
        import json
        with open(os.path.join(folder, "settings.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_blocks_survive_a_load_save_round_trip(self):
        folder = self._folder()
        self._write(folder, {"users": {
            "aa11": {"thumbsize": 64},
            "bb22": {"thumbsize": 256, "view_mode": "list"}}})
        p = self._prefs_at(folder)
        p.load()
        p.save()
        raw = self._read(folder)["users"]
        self.assertEqual({"thumbsize": 64}, raw["aa11"])
        self.assertEqual({"thumbsize": 256, "view_mode": "list"},
                         raw["bb22"])

    def test_junk_shapes_load_without_raising_and_die_on_save(self):
        """load() may not raise, and refresh_data() rewrites the key from the attribute, so junk cannot ride the unknown-key courtesy forever."""
        for junk in (5, "x", [1], {"a-uid": "not-a-dict"},
                     {"a-uid": None}):
            with self.subTest(users=junk):
                folder = self._folder()
                self._write(folder, {"users": junk})
                p = self._prefs_at(folder)
                p.load()
                p.save()
                self.assertEqual({}, self._read(folder)["users"])

    def test_a_uid_this_pane_lacks_arrives_whole(self):
        folder = self._folder()
        self._write(folder, {})
        p = self._prefs_at(folder)
        p.load()
        p._users_blocks["aa11"] = {"thumbsize": 64}
        # Another pane saved since this one read - its user, its block.
        self._write(folder, {"users": {"bb22": {"view_mode": "list"}}})
        p.save()
        raw = self._read(folder)["users"]
        self.assertEqual({"thumbsize": 64}, raw["aa11"],
                         "this pane's block was lost to the merge")
        self.assertEqual({"view_mode": "list"}, raw["bb22"],
                         "the other pane's user was dropped")

    def test_inside_a_shared_uid_ours_wins_per_key(self):
        folder = self._folder()
        self._write(folder, {})
        p = self._prefs_at(folder)
        p.load()
        p._users_blocks["aa11"] = {"thumbsize": 64}
        self._write(folder, {"users": {
            "aa11": {"thumbsize": 512, "view_mode": "list"}}})
        p.save()
        raw = self._read(folder)["users"]["aa11"]
        self.assertEqual(64, raw["thumbsize"],
                         "the active editor's value lost to the peer")
        self.assertEqual("list", raw["view_mode"],
                         "a key only the peer held was dropped")


class TheTestLibrarySwitchIsAnOverlay(unittest.TestCase):
    """One switch, one folder - and the contract that matters is the way BACK: the real library and cache paths stay untouched while it is on."""

    REAL_LIB = "/Users/someone/Cloud/3D/Library/"
    REAL_CACHE = "/Users/someone/Library/Caches/Amaze"

    def _prefs(self):
        p = prefs_mod.Prefs()
        p.dir = self.REAL_LIB
        p.cache_dir = self.REAL_CACHE
        return p

    def test_on_moves_the_library_into_the_folder(self):
        p = self._prefs()
        p.test_dir = "/tmp/amaze_probe"
        p.test_mode = True
        self.assertEqual("/tmp/amaze_probe/lib/", p.dir)
        self.assertEqual(
            self.REAL_CACHE, p.cache_dir,
            "the cache moved with the library, but File thumbnails are "
            "keyed by file path and say nothing about the library")

    def test_the_overlay_and_the_saved_pointer_take_one_shape(self):
        """The test path and the saved `directory` are shaped by one helper, as each copy did."""
        from amaze.prefs import persistence
        for raw, shaped in (("C:\\Lib\\3D", "C:/Lib/3D/"),
                            ("/srv/lib/", "/srv/lib/"),
                            ("/srv/lib", "/srv/lib/"), ("", "")):
            self.assertEqual(shaped, persistence._normalised_dir(raw))
            p = prefs_mod.Prefs()
            p.path = tempfile.mkdtemp(prefix="amaze_dir_shape_")
            self.addCleanup(shutil.rmtree, p.path, True)
            p._directory = raw
            p.refresh_data()
            self.assertEqual(shaped, p.real_dir,
                             "the saved pointer took another shape")
        self.assertEqual("C:/Lib/lib/", prefs_mod.test_library_dir("C:\\Lib"))

    def test_the_real_paths_survive_the_round_trip(self):
        """The one that would cost a real library if it broke."""
        p = self._prefs()
        self.assertFalse(p.test_mode, "the test library is on by default")
        p.test_dir = "/tmp/amaze_probe"
        p.test_mode = True
        p.test_mode = False
        self.assertEqual(self.REAL_LIB, p.dir)
        self.assertEqual(self.REAL_CACHE, p.cache_dir)

    def test_on_with_no_folder_chosen_changes_nothing(self):
        """Half-configured, between ticking the box and picking a folder: answering `/lib/` would point the library at the filesystem root."""
        p = self._prefs()
        p.test_mode = True
        self.assertEqual(self.REAL_LIB, p.dir)
        self.assertEqual(self.REAL_CACHE, p.cache_dir)

    def test_a_fresh_folder_is_seeded_into_a_real_library(self):
        folder = tempfile.mkdtemp(prefix="amaze_testlib_seed_")
        self.addCleanup(shutil.rmtree, folder, True)

        ok, what = prefs_mod.seed_test_folder(folder)

        self.assertTrue(ok, what)
        self.assertTrue(os.path.isdir(os.path.join(folder, "lib")))
        self.assertFalse(
            os.path.isdir(os.path.join(folder, "cache")),
            "a cache folder was made - the cache does not move")
        index = os.path.join(folder, "lib", "library.json")
        self.assertTrue(os.path.isfile(index),
                        "no library.json - the library would not load")
        import json
        with open(index, encoding="utf-8") as handle:
            self.assertEqual(["_All"], json.load(handle)["categories"])

    def test_seeding_never_overwrites_what_is_already_there(self):
        """Run twice, or run on a folder already holding saved test materials: the second pass must add nothing."""
        import json
        folder = tempfile.mkdtemp(prefix="amaze_testlib_reseed_")
        self.addCleanup(shutil.rmtree, folder, True)
        prefs_mod.seed_test_folder(folder)
        index = os.path.join(folder, "lib", "library.json")
        with open(index, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All", "metal"], "tags": [],
                       "assets": [{"id": "mat_001"}]}, handle)

        ok, _what = prefs_mod.seed_test_folder(folder)

        self.assertTrue(ok)
        with open(index, encoding="utf-8") as handle:
            kept = json.load(handle)
        self.assertEqual([{"id": "mat_001"}], kept["assets"],
                         "re-seeding erased the test library's content")

    def test_a_test_library_loads_where_no_real_one_was_ever_configured(self):
        """load() has to ask `dir`, not the raw field behind it: on a machine that has never had a real library the two disagree completely."""
        folder = tempfile.mkdtemp(prefix="amaze_testlib_load_")
        self.addCleanup(shutil.rmtree, folder, True)
        settings = tempfile.mkdtemp(prefix="amaze_testlib_settings_")
        self.addCleanup(shutil.rmtree, settings, True)
        prefs_mod.seed_test_folder(folder)

        p = prefs_mod.Prefs()
        p.path = settings
        p.test_dir = folder
        p.test_mode = True
        p.save()

        fresh = prefs_mod.Prefs()
        fresh.path = settings
        self.assertTrue(
            fresh.load(),
            "a seeded test library did not load on a machine with no "
            "real library, so the panel opens libraryless over it")
        self.assertEqual(prefs_mod.test_library_dir(folder), fresh.dir,
                         "the switch is on but the overlay is not what "
                         "the library reads")
        self.assertEqual(
            "", fresh.real_dir,
            "the fixture stopped proving the bug - it now configures a "
            "REAL library, and that case passed before the fix too")


class TheHomeLayoutsLiveInHostos(unittest.TestCase):

    def test_rehome_only_answers_when_the_result_exists(self):
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        self.assertEqual(
            "/Users/someone-else/definitely/not/here",
            hostos.rehome("/Users/someone-else/definitely/not/here"),
            "rehome rewrote a path whose target does not exist - the "
            "existence check is the only thing stopping a shared "
            "/home/projects mount being rewritten into this user's home")
        # And it does answer for something that does exist.
        self.assertEqual(
            home + "/", hostos.rehome("/Users/someone-else/"))
        self.assertEqual(
            "D:/Profiles/someone/lib",
            hostos.rehome("D:/Profiles/someone/lib"),
            "a redirected Windows profile was rewritten - it is not a "
            "recognised layout and must be left as it is")


class OnlineDownloadsStayInsideTheLibrary(unittest.TestCase):

    def test_no_hand_rolled_containment_is_left(self):
        """`contained_join` resolves REALPATHS, so a planted symlink cannot be the hop out - which a normpath comparison cannot see."""
        body = source_of("core/matx_sources.py")
        self.assertNotIn(
            "os.path.normpath(os.path.join(dest_dir", body,
            "a download path is checked by normpath again")
        tree = ast.parse(body)  # by AST, per target: counting occurrences stayed green with one check removed
        rgl_checked = False
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") == "contained_join"):
                continue
            if "_rgb.bsdf" in ast.dump(node):
                rgl_checked = True
        self.assertTrue(
            rgl_checked,
            "the RGL measurement download composes its path without "
            "contained_join - and its uid comes from the remote "
            "catalogue, so `../x` writes outside the cache root")

    def test_a_failed_package_lookup_is_not_cached(self):
        """`_packages` swallows every per-package error and returns [], and an empty list is a PRESENT key - so a cached failure would outlive the network blip."""
        from amaze.core import matx_sources

        for answer, lookups in (([], 2),
                                ([("2K", "id", "http://example/x.zip")], 1)):
            with self.subTest(packages=answer):

                class Record:
                    payload = {}
                    title = "Red Brick"

                class Source(matx_sources.GPUOpenSource):
                    def __init__(self):
                        self.calls = 0

                    def _packages(self, record):
                        self.calls += 1
                        return list(answer)

                source = Source()
                record = Record()
                source._resolved_packages(record)
                source._resolved_packages(record)
                self.assertEqual(
                    lookups, source.calls,
                    "a failed lookup was cached, so the retry never "
                    "reached the network - or a good one was not cached")
                if not answer:
                    self.assertNotIn(
                        "_resolved", record.payload,
                        "the failure was written onto the record")


class RefreshDropsEveryCacheASourceKeeps(unittest.TestCase):
    """Refresh is the user asking us to go and LOOK - a cache that survives it serves yesterday's site until restart."""

    def test_gpuopen_refresh_drops_the_category_map(self):
        from amaze.core import matx_sources
        source = matx_sources.GPUOpenSource()
        source._categories = {"1": "Metals"}
        source.refresh()
        self.assertIsNone(
            source._categories,
            "the category map survived Refresh - a renamed remote "
            "category files its materials under Uncategorized until "
            "Houdini restarts")


class TheShippedTableIsClosedAfterTheSizeCheck(unittest.TestCase):

    def test_judging_a_live_answer_leaves_no_file_open(self):
        """`_usable` reads the shipped table to size a live answer, and closes it."""
        import gc
        import warnings
        from amaze.core import matx_sources
        live = [{"name": "M%d" % n, "color": [0.5, 0.5, 0.5]}
                for n in range(200)]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            matx_sources.PhysicallyBasedSource()._usable(live)
            gc.collect()
        self.assertEqual(
            [], [str(w.message) for w in caught
                 if issubclass(w.category, ResourceWarning)],
            "the shipped table was left open after the size check")


class AFullSourceIsLogged(unittest.TestCase):

    def _source(self, name, short_by):
        class Source:
            def list_materials(self, search="", offset=0, limit=60):
                return [object()] * (limit - short_by)
        found = Source()
        found.name = name
        return found

    def test_a_source_that_fills_the_cap_says_so(self):
        """No source fills the cap today; the log says when one starts to."""
        from amaze.core import matx_library
        from amaze.tests import test_support
        with test_support.captured_log() as log:
            matx_library._CatalogueWorker(
                [self._source("Full", 0), self._source("Short", 1)],
                0).run()
        full = [r["data"].get("source")
                for r in log.records("online")
                if "cap" in str(r.get("msg", ""))]
        self.assertEqual(["Full"], full,
                         "a source that filled the catalogue cap left "
                         "no line in the log, or a short one did")


class TheCatalogueCacheLandsWhole(unittest.TestCase):
    """The on-disk Online catalogue is replaced whole or not at all."""

    def test_a_write_that_dies_part_way_keeps_the_last_catalogue(self):
        import json

        from amaze.tests import test_support
        from amaze.core import matx_library, matx_sources
        path = matx_library.catalogue_cache()
        self.assertTrue(path.startswith(test_support.TEST_CACHE),
                        "premise: the catalogue is not in the test cache")
        if os.path.exists(path):
            shutil.copy2(path, path + ".kept")
            self.addCleanup(shutil.move, path + ".kept", path)
        else:
            self.addCleanup(
                lambda: os.path.exists(path) and os.remove(path))
        model = matx_library.MatxOnlineLibrary.__new__(
            matx_library.MatxOnlineLibrary)
        model._save_cache([matx_sources.MatxRecord(
            source="GPUOpen", uid="u%d" % n, title="M%d" % n)
            for n in range(3)])
        self.assertEqual(3, len(model._load_cache() or ()),
                         "premise: the first catalogue did not land")

        def torn(obj, handle, *args, **kwargs):
            handle.write('{"records": [{"sou')
            raise OSError(28, "No space left on device")

        with mock.patch.object(json, "dump", torn):
            with test_support.captured_log():
                model._save_cache([matx_sources.MatxRecord(
                    source="GPUOpen", uid="x", title="X")])
        self.assertEqual(
            3, len(model._load_cache() or ()),
            "a write that died part-way left a torn catalogue, so the "
            "next Online open loses the whole cached list")


class ARemapOnAColourChainStillRemaps(unittest.TestCase):
    """mtlxremap and mtlxclamp are signature-polymorphic: wiring a color3 source flips the LIVE parm to the `_color3` variant, so the range values must go through `_set_poly_parm` or they land on the inert plain parm and the remap renders as a no-op."""

    def test_the_range_values_reach_the_live_parm_variant(self):
        from amaze.render import material_converter as mc
        parent = hou.node("/mat")
        if parent is None:
            self.skipTest("no /mat context in this build")
        dest = parent.createNode("subnet")
        self.addCleanup(dest.destroy)
        image = dest.createNode("mtlximage")
        image.parm("signature").set("color3")

        class _Parm:
            def __init__(self, value):
                self._value = value

            def eval(self):
                return self._value

        class _Type:
            def name(self):
                return "redshift::RSMathRange"

        class _RS:
            def type(self):
                return _Type()

            def name(self):
                return "range1"

            def path(self):
                return "/stub/range1"

            def inputs(self):
                return (object(),)

            def inputNames(self):
                return ("input",)

            def parm(self, name):
                return {"old_min": _Parm(0.25), "old_max": _Parm(0.75),
                        "new_min": _Parm(0.1), "new_max": _Parm(0.9),
                        "clamp": _Parm(1)}.get(name)

        report = mc.ConversionReport("range fixture")
        with mock.patch.object(mc, "convert_node", return_value=image):
            out = mc.convert_math_range(_RS(), dest, report)

        remap = next(n for n in dest.children()
                     if n.type().name() == "mtlxremap")
        self.assertEqual("color3", remap.parm("signature").evalAsString(),
                         "premise: wiring the color3 image flipped the "
                         "remap's signature")
        self.assertEqual(
            (0.25, 0.25, 0.25), tuple(remap.parmTuple("inlow_color3").eval()),
            "old_min never reached the LIVE inlow variant - the remap "
            "renders with its identity defaults")
        self.assertEqual("mtlxclamp", out.type().name(),
                         "premise: clamp on appends an mtlxclamp")
        self.assertEqual(
            (0.1, 0.1, 0.1), tuple(out.parmTuple("low_color3").eval()),
            "new_min never reached the clamp's LIVE low variant")


class VendorTransformsAreOpenPBRsAlone(unittest.TestCase):
    """The fuzz^2.5 curve and the coat-roughness mix come from the OpenPBR translation graph - run on StandardMaterial or the classic shader they silently rewrite values the 1:1 maps copied correctly."""

    def test_only_the_openpbr_door_runs_them(self):
        from amaze.render import material_converter as mc
        parent = hou.node("/mat")
        if parent is None:
            self.skipTest("no /mat context in this build")
        dest = parent.createNode("subnet")
        self.addCleanup(dest.destroy)

        class _Type:
            def name(self):
                return "redshift::StandardMaterial"

        class _RS:
            def type(self):
                return _Type()

            def name(self):
                return "shader1"

            def path(self):
                return "/stub/shader1"

            def inputs(self):
                return ()

            def inputNames(self):
                return ()

            def parm(self, _name):
                return None

            def parmTuple(self, _name):
                return None

        report = mc.ConversionReport("uber fixture")
        with mock.patch.object(mc, "_apply_vendor_transforms") as vendor:
            mc.convert_standard_material(_RS(), dest, report)
            self.assertEqual(0, vendor.call_count,
                             "the OpenPBR-only transforms ran on a "
                             "StandardMaterial conversion")
            mc.convert_classic_material(_RS(), dest, report)
            self.assertEqual(0, vendor.call_count,
                             "the OpenPBR-only transforms ran on a "
                             "classic-shader conversion")
            mc.convert_openpbr_material(_RS(), dest, report)
            self.assertEqual(1, vendor.call_count,
                             "the OpenPBR door lost its own transforms")


class ConvertNodeCarriesTheTargetInput(unittest.TestCase):
    """The dispatcher hands `target_input` to every converter whose signature takes it, so a texture nested behind one still converts with its role."""

    def test_a_converter_that_accepts_it_receives_it(self):
        from amaze.render import material_converter as mc

        received = {}

        def takes(rs_node, dest_parent, report, target_input=""):
            received["takes"] = target_input
            return None

        def bare(rs_node, dest_parent, report):
            received["bare"] = True
            return None

        class _Type:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        class _Node:
            def __init__(self, type_name):
                self._type = _Type(type_name)

            def type(self):
                return self._type

            def name(self):
                return "stub"

        mc.NODE_CONVERTERS["stub::Takes"] = takes
        mc.NODE_CONVERTERS["stub::Bare"] = bare

        def _unregister():
            mc.NODE_CONVERTERS.pop("stub::Takes", None)
            mc.NODE_CONVERTERS.pop("stub::Bare", None)

        self.addCleanup(_unregister)
        report = mc.ConversionReport("stub")
        mc.convert_node(_Node("stub::Takes"), None, report, "base_color")
        mc.convert_node(_Node("stub::Bare"), None, report, "base_color")
        self.assertEqual(
            "base_color", received.get("takes"),
            "the dispatcher dropped target_input for a converter that "
            "forwards it - the nested texture reads as data/Raw")
        self.assertTrue(received.get("bare"),
                        "a converter without the parameter broke")


class AHalfFetchedPackageIsNotReused(unittest.TestCase):
    """The fetch lands in a scratch sibling and is renamed over only on success, so an occupied destination IS a complete package."""

    def _record(self):
        class Record:
            kind = "package"
            uid = "seam1"
            title = "Seam Test"
            source = "stub"
            payload = {}

        return Record()

    def test_a_fetch_that_dies_leaves_no_destination(self):
        from amaze.core import matx_import
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)

        class DyingSource:
            name = "stub"

            def fetch(self, record, resolution, dest_dir, progress=None):
                os.makedirs(dest_dir, exist_ok=True)
                with open(os.path.join(dest_dir, "texture_part.png"),
                          "wb") as handle:
                    handle.write(b"HALF")
                raise RuntimeError("connection dropped")

        class NoMtlxSource:
            name = "stub"

            def fetch(self, record, resolution, dest_dir, progress=None):
                os.makedirs(dest_dir, exist_ok=True)
                with open(os.path.join(dest_dir, "wood_diffuse.png"),
                          "wb") as handle:
                    handle.write(b"PNG")
                return {"mtlx": None}

        for source, why in ((DyingSource(), "connection dropped"),
                            (NoMtlxSource(), "No .mtlx")):
            with self.subTest(why=why):
                record = self._record()
                produce, _note, error = matx_import._producer_for(
                    record, source, "2K", prefs)
                self.assertIsNone(produce)
                self.assertIn(why, error)
                dest = os.path.join(matx_import.matx_dir(prefs.dir),
                                    matx_import.package_dirname(record))
                self.assertFalse(
                    os.path.isdir(dest) and os.listdir(dest),
                    "a dead or .mtlx-less fetch occupied the destination - "
                    "every later import reuses or refuses it")

    def test_the_retry_fetches_fresh_and_lands_complete(self):
        from amaze.core import matx_import
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)

        class Source:
            name = "stub"

            def fetch(self, record, resolution, dest_dir, progress=None):
                os.makedirs(dest_dir, exist_ok=True)
                path = os.path.join(dest_dir, "seam.mtlx")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write('<?xml version="1.0"?>\n'
                                 '<materialx version="1.38">\n'
                                 "</materialx>\n")
                return {"mtlx": path}

        record = self._record()
        produce, _note, error = matx_import._producer_for(
            record, Source(), "2K", prefs)
        self.assertEqual("", error)
        self.assertIsNotNone(produce)
        dest = os.path.join(matx_import.matx_dir(prefs.dir),
                            matx_import.package_dirname(record))
        self.assertTrue(
            os.path.isfile(os.path.join(dest, "seam.mtlx")),
            "the completed fetch never landed at the destination")
        self.assertFalse(
            os.path.isdir(dest + ".downloading"),
            "the scratch sibling survived a successful fetch")


class ANoVariantAssetRefusesWithAReason(unittest.TestCase):
    """`StopIteration`'s str() is EMPTY, so an asset shipping no .mtlx variant has to name itself in the refusal or the message says nothing."""

    def test_fetch_with_no_variants_names_the_asset(self):
        from amaze.core import matx_sources

        class Source(matx_sources.PolyHavenSource):
            def __init__(self):
                pass

            def _files(self, record):
                return {}

        class Record:
            title = "Bare Rock"
            payload = {}

        with self.assertRaisesRegex(RuntimeError, "Bare Rock"):
            Source().fetch(Record(), "2K", "/nowhere")


class StagingLeavesNoUndoEntry(unittest.TestCase):
    """A container is STAGING when one function creates it and destroys it in a `finally`, and both halves must then sit inside `hou.undos.disabler()`. ▸r/undo-groups"""

    FILES = ("core/matx_import.py", "core/gallery_import.py",  # every file that scaffolds a scene; `render/thumbs.py` holds more of it than any other
             "render/nodes.py", "render/material_converter.py",
             "core/library.py", "render/thumbs.py")

    def test_every_staging_pair_is_off_the_stack(self):
        offenders = []
        pairs = 0
        for rel in self.FILES:
            body = source_of(rel)
            tree = ast.parse(body)
            guarded_ranges = [  # a disabler guards its LEXICAL block, so this reads scope and never a line window
                (node.lineno, node.end_lineno)
                for node in ast.walk(tree)
                if isinstance(node, ast.With)
                and "disabler" in ast.dump(node.items[0].context_expr)]

            def guarded(lineno):
                return any(first <= lineno <= last
                           for first, last in guarded_ranges)

            for func in ast.walk(tree):
                if not isinstance(func, ast.FunctionDef):
                    continue
                creates = {}  # EVERY create for a name, not the last: one variable assigned in two branches let a guarded sibling vouch for an unguarded create
                for node in ast.walk(func):
                    if (isinstance(node, ast.Assign)
                            and len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Name)
                            and isinstance(node.value, ast.Call)
                            and getattr(node.value.func, "attr", "")
                            == "createNode"):
                        creates.setdefault(
                            node.targets[0].id, []).append(node.lineno)
                if not creates:
                    continue
                finally_ranges = [
                    (node.finalbody[0].lineno,
                     node.finalbody[-1].end_lineno)
                    for node in ast.walk(func)
                    if isinstance(node, ast.Try) and node.finalbody]
                for node in ast.walk(func):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "destroy"
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id in creates):
                        continue
                    if not any(first <= node.lineno <= last
                               for first, last in finally_ranges):
                        continue          # a failure rollback - a RESULT
                    name = node.func.value.id
                    pairs += 1
                    halves = [("created", line) for line in creates[name]]
                    halves.append(("destroyed", node.lineno))
                    for half, lineno in halves:
                        if not guarded(lineno):
                            offenders.append(
                                "%s:%d (%s, %s)"
                                % (rel, lineno, name, half))
        self.assertGreaterEqual(
            pairs, 8,
            "the scan matched %d staging pairs where the tree holds "
            "about ten - it has gone vacuous, not clean" % pairs)
        self.assertEqual(
            [], offenders,
            "these put half of a staging pair on the LIVE undo stack, "
            "so one Ctrl+Z resurrects the container with its "
            "children: %s" % offenders)


class AGalleryIsLeftAsItWasFound(unittest.TestCase):

    def test_OperationFailed_really_is_covered_by_hou_Error(self):
        """The premise for dropping it from the except tuple - if Houdini ever unhooks the two, the narrowed clause stops catching it. ▸r/gallery-entries"""
        self.assertTrue(
            issubclass(hou.OperationFailed, hou.Error),
            "hou.OperationFailed is no longer a hou.Error, so the "
            "removeGallery clause silently stopped catching it")


class SettingsAreNotWrittenPerMouseMove(unittest.TestCase):

    def test_close_still_persists(self):
        self.assertTrue(
            calls("dialogs/prefs_dialog.py", "closeEvent", "save"),
            "nothing persists the dialog's values any more")

    def test_the_ram_slider_leaves_persistence_to_close(self):
        """ClickSlider fires on every mouse move, so saving per tick fsyncs settings.json all drag."""
        self.assertFalse(
            calls("dialogs/prefs_dialog.py", "set_ram_cache_mb", "save"),
            "the RAM Cache setter saves on every tick again")


class TheFileLoaderQueueDoesNotBusySpin(unittest.TestCase):

    def test_it_re_arms_on_a_frame_not_immediately(self):
        """A zero-delay re-arm spins the handler at full event-loop rate on the painting thread."""
        tree = ast.parse(source_of("core/thumbnails.py"))
        delays = []    # the RE-ARM only: the first schedule has nothing to wait for
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "_dispatch_files"):
                continue
            for branch in ast.walk(node):
                if not (isinstance(branch, ast.If)
                        and "FILE_LOADER_LIMIT" in ast.dump(branch.test)):
                    continue
                for call in ast.walk(branch):
                    if (isinstance(call, ast.Call)
                            and getattr(call.func, "attr", "") == "singleShot"
                            and call.args and isinstance(call.args[0], ast.Constant)):
                        delays.append(call.args[0].value)
        self.assertTrue(delays, "the cap's re-arm is gone entirely")
        self.assertTrue(all(d > 0 for d in delays),
                        "the file-loader queue re-arms with a zero delay: %s" % delays)


class OneRuleForWhatBelongsInAFolder(unittest.TestCase):

    def test_the_two_answers_cannot_disagree(self):
        class Prefs:
            file_show_unknown = False
            file_folder_show_all = {}

        model = file_library.FileFolders.__new__(file_library.FileFolders)
        model.preferences = Prefs()
        for name in ("thing.png", "thing.bgeo.sc", "thing.hip",
                     "thing.wat", ".hidden"):
            self.assertEqual(
                model.matches_in("", name), model.matches(name),
                "the flat and per-location answers disagree for %r"
                % name)


class TheOsHandOffsNeverRaise(unittest.TestCase):
    """The log buttons call these unguarded: a refused or missing handler is swallowed inside."""

    def test_no_platform_branch_raises_when_every_handler_fails(self):
        def refuse(*_args, **_kwargs):
            raise FileNotFoundError("no such program")

        for mac, windows in ((True, False), (False, True), (False, False)):
            with self.subTest(macos=mac, windows=windows), \
                    mock.patch.object(hostos, "is_macos",
                                      return_value=mac), \
                    mock.patch.object(hostos, "is_windows",
                                      return_value=windows), \
                    mock.patch.object(hostos.subprocess, "call",
                                      side_effect=refuse), \
                    mock.patch.object(hostos.os, "startfile", create=True,
                                      side_effect=OSError("no app")):
                hostos.open_path("/nowhere/amaze_debug.jsonl")
                hostos.reveal_path("/nowhere/amaze_debug.jsonl")


class TheUserRowCreatesAndDeletes(unittest.TestCase):
    """Preferences > User grew create and delete beside rename (settled 2026-08-22): the combo carries the picker's own create row, deletion sweeps everything tagged theirs, and the row goes blank on self-delete until somebody is picked."""

    def test_the_user_row_offers_create_and_delete(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog, user_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.library_user = users.create(p, "Cobalt")
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combo = dlg.cbb_library_user
        sentinel = user_dialog.UserPickerDialog.CREATE
        rows = [combo.itemData(i) for i in range(combo.count())]
        self.assertIn(sentinel, rows,
                      "the row cannot create a user - the picker "
                      "dialog's create entry is missing here")
        self.assertEqual(sentinel, rows[-1],
                         "the create entry is not the LAST row, so it "
                         "reads as a user called Create")
        self.assertTrue(dlg._btn_delete_user.isEnabled())

    def test_the_row_and_the_picker_list_the_same_rows(self):
        """One filler: the first-open picker and Preferences show the same rows in the same order."""
        from amaze.core import users
        from amaze.dialogs import prefs_dialog, user_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        for name in ("sienna", "Cobalt", "Fern"):
            p.library_user = users.create(p, name)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        picker = user_dialog.UserPickerDialog(users.all_users(p))
        self.addCleanup(picker.deleteLater)

        def rows(combo):
            return [(combo.itemText(i), combo.itemData(i))
                    for i in range(combo.count())]

        self.assertEqual(rows(picker._combo), rows(dlg.cbb_library_user))
        self.assertEqual(["Cobalt", "Fern", "sienna"],
                         [text for text, _ in rows(picker._combo)[:-1]],
                         "the users are not listed by name, A to Z")

    def test_a_quiet_set_emits_nothing_and_keeps_an_outer_block(self):
        from amaze.dialogs import prefs_dialog
        from amaze.helpers import ui_helpers
        box = ui_helpers.ToggleSwitch("Probe")
        self.addCleanup(box.deleteLater)
        heard = []
        box.toggled.connect(heard.append)
        prefs_dialog._show_quietly(box, True)
        self.assertEqual(([], True, False),
                         (heard, box.isChecked(), box.signalsBlocked()))
        box.blockSignals(True)
        prefs_dialog._show_quietly(box, False)
        self.assertTrue(box.signalsBlocked(),
                        "a quiet set unblocked a caller's own block")

    def test_a_created_user_is_made_and_switched_to_on_apply(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.library_user = users.create(p, "Cobalt")
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        dlg.create_library_user("  Fern  ")
        self.assertEqual({"Cobalt"}, set(users.all_users(p).values()),
                         "the user was made before Apply")
        self.assertEqual("Fern", dlg.cbb_library_user.currentText())
        self.assertTrue(dlg.apply_library())
        self.assertEqual({"Cobalt", "Fern"}, set(users.all_users(p).values()))
        self.assertEqual("Fern", users.name_for(p, p.library_user),
                         "Apply did not switch this computer to the new user")
        self.assertEqual("Fern", dlg.cbb_library_user.currentText())

    def test_deleting_the_current_user_adopts_nobody(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        first = users.create(p, "Cobalt")
        users.create(p, "Sienna")
        users.create(p, "Fern")
        p.library_user = first
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        dlg.delete_library_user(first)
        self.assertEqual({"Sienna", "Fern"}, set(users.all_users(p).values()))
        self.assertEqual("", str(p.library_user or ""))
        self.assertEqual(-1, dlg.cbb_library_user.currentIndex(),
                         "a user was picked in a library of several with no match")
        self.assertFalse(dlg._btn_edit_user.isEnabled())
        self.assertFalse(dlg._btn_delete_user.isEnabled())
        self.assertFalse(dlg._btn_apply_library.isEnabled(),
                         "Apply runs with nobody picked")

    def test_the_only_user_left_is_picked_and_waits_for_apply(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        first = users.create(p, "Cobalt")
        users.create(p, "Sienna")
        p.library_user = first
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        dlg.delete_library_user(first)
        self.assertEqual("Sienna", dlg.cbb_library_user.currentText(),
                         "the library's only user was not picked")
        self.assertEqual("", str(p.library_user or ""),
                         "the only user was adopted before Apply")


class ACancelledTestFolderPickIsANoOp(unittest.TestCase):
    """Turning Test Library on with no folder asks for one; cancelling the ask applied NOTHING, so the revert must not switch every model on its way back."""

    def test_the_revert_does_not_switch_the_library(self):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        applied = []
        dlg._apply_test_mode = lambda: applied.append(True)
        dlg.change_test_path = lambda: None
        dlg._cbx_test_mode.setChecked(True)
        self.assertFalse(p.test_mode)
        self.assertFalse(dlg._cbx_test_mode.isChecked())
        self.assertEqual(
            [], applied,
            "the revert re-entered set_test_mode and ran the full "
            "library switch for a gesture that applied nothing")


class TheOverwriteSwitchFollowsTheLibrary(unittest.TestCase):
    """The switch is read from the policy file ONCE, at construction - a library switch under the open dialog must re-read it, or the switch shows the previous library's policy."""

    def test_switching_libraries_rereads_the_overwrite_policy(self):
        from amaze.core import library_policy
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        library_policy.set_allow_overwrite(p.dir, False)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg._cbx_allow_overwrite.isChecked(),
                         "premise: the first library forbids overwrite")
        folder = test_support.scratch_dir("amaze_policy_switch_")
        self.addCleanup(shutil.rmtree, folder, True)
        ok, _ = prefs_mod.seed_test_folder(folder)
        self.assertTrue(ok, "premise: the test folder seeds")
        p.test_dir = folder
        p.test_mode = True
        dlg._apply_test_mode()
        self.assertTrue(
            dlg._cbx_allow_overwrite.isChecked(),
            "the switch still shows the PREVIOUS library's policy - a "
            "library with no policy.json allows overwrite")


class TheCacheWipeCannotBeSuppressed(unittest.TestCase):
    """`hou.ui.displayConfirmation` defaults `suppress` to `hou.confirmType.OverwriteFile` - Houdini's GLOBAL do-not-ask-again flag for file overwrites - so left at the default this destructive wipe stops asking the moment that box is ticked anywhere in the application."""

    def _asked_with(self, dlg):
        seen = {}

        def confirm(text, *_args, **kwargs):
            seen["text"] = text
            seen["kwargs"] = kwargs
            return False   # Cancel, so the method returns before any cache is touched and the fixture library survives

        with mock.patch.object(
                hou, "ui",
                types.SimpleNamespace(displayConfirmation=confirm),
                create=True):
            dlg.clear_texture_cache()
        return seen

    def test_the_wipe_asks_with_the_non_suppressable_type(self):
        from amaze import messages
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        seen = self._asked_with(dlg)
        self.assertIn("kwargs", seen, "the wipe never asked at all")
        self.assertEqual(messages.CONFIRM_CLEAR_THUMBNAIL_CACHE,
                         seen.get("text"))
        self.assertEqual(
            hou.confirmType.NoConfirmType, seen["kwargs"].get("suppress"),
            "the cache wipe rides on a SUPPRESSABLE confirmation: with "
            "`suppress` at its default of `hou.confirmType.OverwriteFile`, "
            "one tick of do-not-ask-again anywhere in Houdini deletes every "
            "cached thumbnail with no question asked")


class PreferencesSpeakTheDrawnWords(unittest.TestCase):
    """Three Preferences messages take the drawn wording from `messages.py`, not an inline copy."""

    def _dialog(self):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_the_material_versions_help(self):
        from amaze import messages
        from amaze.core import library_policy
        dlg = self._dialog()
        library_policy.set_allow_overwrite(dlg._prefs.dir, False)
        seen = {}

        def display(text, *_args, **kwargs):
            seen.update(kwargs, text=text)
            return 1    # Cancel, so nothing is written

        with mock.patch.object(hou, "ui",
                               types.SimpleNamespace(displayMessage=display),
                               create=True):
            dlg.set_allow_overwrite(True)
        self.assertEqual(messages.MATERIAL_VERSIONS_TURN_ON_CONFIRM,
                         seen.get("text"), "premise: the confirm was asked")
        self.assertEqual(messages.HELP_MATERIAL_VERSIONS, seen.get("help"))

    def test_the_log_save_failure(self):
        from amaze import messages
        from amaze.core import debug
        from amaze.tests import test_support
        dlg = self._dialog()
        folder = test_support.scratch_dir("amaze_log_save_")
        self.addCleanup(shutil.rmtree, folder, True)
        failure = OSError("the disk is full")
        shown = []
        with mock.patch.object(QtWidgets.QFileDialog, "getExistingDirectory",
                               return_value=folder), \
                mock.patch.object(debug, "export_log", side_effect=failure), \
                mock.patch.object(QtWidgets.QMessageBox, "warning",
                                  lambda *args: shown.append(args)):
            dlg.save_debug_log()
        self.assertEqual(1, len(shown), "premise: the failure was shown")
        self.assertEqual(messages.LOG_NOT_SAVED_UNEXPECTED % failure,
                         shown[0][2])


class ThePickersStartInAForwardSlashPath(unittest.TestCase):
    """`hou.ui.selectFile` documents `start_directory` as forward slashes on Windows, and `os.path.join` there hands out backslashes - so an os.sep-flavoured path has to be canonicalised before it is passed."""

    def _started_in(self, method):
        seen = {}

        def select_file(*_args, **kwargs):
            seen.update(kwargs)
            return ""   # Cancel, so the method returns before writing a preference

        # os.sep is the ONLY difference between the two platforms inside `hostos.canonical_path_key`, so patching it runs this host through the Windows reading of the same code.
        with mock.patch.object(os, "sep", "\\"), mock.patch.object(
                hou, "ui",
                types.SimpleNamespace(selectFile=select_file),
                create=True):
            method()
        return seen.get("start_directory", "")

    def _dialog(self, prefs_obj):
        from amaze.dialogs import prefs_dialog
        dlg = prefs_dialog.PrefsDialog(prefs_obj, panel=None)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_the_cache_picker_starts_in_a_forward_slash_path(self):
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.cache_dir = ""   # unset, which is the branch that falls through to the machine's own convention - the one `os.path.join` builds
        dlg = self._dialog(p)
        from amaze.dialogs import prefs_dialog
        native = "C:\\scratch\\AppData\\Local\\Amaze\\Cache"
        with mock.patch.object(prefs_dialog.hostos, "cache_root",   # the dialog's OWN reference, since a fixture panel reloads hostos and this module's import can be the older object
                               lambda: native):
            start = self._started_in(dlg.change_cache_path)
        self.assertEqual(
            "C:/scratch/AppData/Local/Amaze/Cache", start,
            "the cache picker opens on a native Windows path; selectFile "
            "requires forward slashes there and ignores the rest")

    def test_the_test_folder_picker_starts_in_a_forward_slash_path(self):
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.test_dir = "D:\\shots\\amaze_test"   # a stored absolute comes back from settings.json in the spelling it was written in, backslashes and all
        dlg = self._dialog(p)
        start = self._started_in(dlg.change_test_path)
        self.assertEqual(
            "D:/shots/amaze_test", start,
            "the test-folder picker opens on a native Windows path; "
            "selectFile requires forward slashes there and ignores the rest")


class APickedRootKeepsItsSlash(unittest.TestCase):
    """Only a trailing slash that is not the root goes: `D:` is relative to drive D's current folder."""

    WINDOWS_OS = types.SimpleNamespace(path=ntpath, sep="\\")    # what os.path and os.sep are there

    def _picked(self, method, answer, windows=False):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.cache_dir = p.test_dir = "/start"    # so neither picker asks for the machine's cache root
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        seeded = []
        ui = types.SimpleNamespace(selectFile=lambda *_a, **_k: answer,
                                   displayMessage=lambda *_a, **_k: 0)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(hou, "ui", ui, create=True))
            stack.enter_context(mock.patch.object(p, "save", lambda: None))
            stack.enter_context(mock.patch.object(
                prefs_dialog.hostos, "set_cache_override", lambda _path: None))
            stack.enter_context(mock.patch.object(
                prefs_dialog.prefs_mod, "seed_test_folder",
                lambda folder: seeded.append(folder) or (False, "refused")))
            if windows:
                stack.enter_context(mock.patch.object(
                    prefs_dialog.hostos, "os", self.WINDOWS_OS))
            getattr(dlg, method)()
        return p.cache_dir if method == "change_cache_path" else seeded[0]

    def test_a_picked_root_is_kept_whole(self):
        for method in ("change_cache_path", "change_test_path"):
            for answer, windows, kept in (
                    ("/", False, "/"), ("D:/", True, "D:/"),
                    ("/Volumes/cache/", False, "/Volumes/cache"),
                    ("D:/shots/", True, "D:/shots")):
                with self.subTest(picker=method, picked=answer):
                    self.assertEqual(kept,
                                     self._picked(method, answer, windows))


if __name__ == "__main__":
    unittest.main()
