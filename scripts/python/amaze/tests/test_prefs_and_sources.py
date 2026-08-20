"""Prefs, online sources, and the long tail - several of these read the SOURCE, and by AST rather than by text."""

import ast
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import file_library  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402

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
    """ONE renderer table, read by the Filter menu, the Preferences switches and `enable_renderer_on_add` alike."""

    def test_sections_exports_it(self):
        table = sections.renderer_prefs()
        self.assertTrue(table, "the renderer table is empty")
        for label, attr in table:
            self.assertTrue(hasattr(prefs_mod.Prefs, attr),
                            "%s (%s) names no preference" % (label, attr))

    def test_preferences_reads_the_table(self):
        self.assertTrue(
            calls("dialogs/prefs_dialog.py", "_build_showhide_tab",
                  "renderer_prefs"),
            "the Show/Hide tab carries its own copy of the renderer "
            "table again - add a renderer and it gets no switch")

    def test_enable_on_add_reads_the_table(self):
        self.assertTrue(
            calls("panel/panel.py", "enable_renderer_on_add",
                  "renderer_prefs"),
            "enable_renderer_on_add is an if/elif chain again - a new "
            "renderer's first material would be invisible in the tab "
            "it was saved from")

    def test_every_renderer_can_be_switched_on_by_saving_one(self):
        """The behaviour the third copy exists for."""
        class Panel:
            prefs = prefs_mod.Prefs()

            def save(self):
                pass

        from amaze.panel import panel as panel_mod
        fake = Panel()
        fake.prefs.save = lambda: None
        for label, attr in sections.renderer_prefs():
            setattr(fake.prefs, attr, False)
        for label, attr in sections.renderer_prefs():
            panel_mod.MatLibPanel.enable_renderer_on_add(fake, label)
            self.assertTrue(
                getattr(fake.prefs, attr),
                "saving a %s material did not switch %s on, so the "
                "material would be invisible in the tab it was saved "
                "from" % (label, label))


class RendererDefaultsAgree(unittest.TestCase):

    def test_an_empty_directory_loads_the_documented_defaults(self):
        """load() returns before its `.get()` defaults on a machine with no settings file, so __init__'s values are what that machine keeps."""
        empty = tempfile.mkdtemp(prefix="amaze_prefs_defaults_")
        self.addCleanup(shutil.rmtree, empty, True)
        p = prefs_mod.Prefs()
        p.path = empty
        p.load()
        for attr, default in prefs_mod.RENDERER_DEFAULTS.items():
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
        offered = [label for label, attr in sections.renderer_prefs()
                   if getattr(p, attr, False)]
        self.assertIn("Karma", offered)
        self.assertIn("Redshift", offered)


class LoadNeverRaisesAndAlwaysValidates(unittest.TestCase):

    POISON = {  # every key with a validating setter, against the value that breaks it; `null` is the shape a hand edit or a future build's type change produces
        "scroll_speed": None,
        "ram_cache_mb": None,
        "texture_parallel_conversions": "eight",
        "karma_rendersamples": None,
        "view_mode": None,
        "accent_color": None,
    }

    def test_a_poisoned_settings_file_still_loads(self):
        import json
        folder = tempfile.mkdtemp(prefix="amaze_prefs_poison_")
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(self.POISON, handle)

        p = prefs_mod.Prefs()
        p.path = folder
        p.load()          # must not raise: panel._build re-raises

        self.assertIsInstance(p.scroll_speed, float)  # and USABLE: Preferences does arithmetic on these inside a slot where PySide swallows the error
        round(p.scroll_speed * 100)
        self.assertIsInstance(p.ram_cache_mb, int)
        self.assertIsInstance(p.texture_parallel_conversions, int)
        self.assertIsInstance(p.karma_rendersamples, int)
        self.assertIn(p.view_mode, ("grid", "list"))
        self.assertTrue(p.accent_color)

    def test_load_assigns_through_the_setters(self):
        """Source pin on the file holding load(): the values are clamped in the setters, and a raw assignment bypasses every one."""
        body = ast.dump(ast.parse(source_of("prefs/persistence.py")))
        self.assertIn(
            "_through_setter", body,
            "load() assigns these keys raw again")


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

    def test_off_by_default_and_the_real_paths_answer(self):
        p = self._prefs()
        self.assertFalse(p.test_mode)
        self.assertEqual(self.REAL_LIB, p.dir)
        self.assertEqual(self.REAL_CACHE, p.cache_dir)

    def test_on_moves_the_library_into_the_folder(self):
        p = self._prefs()
        p.test_dir = "/tmp/amaze_probe"
        p.test_mode = True
        self.assertEqual("/tmp/amaze_probe/lib/", p.dir)

    def test_the_cache_does_not_move_with_the_library(self):
        """The File section's thumbnails are keyed by file path on disk, so they say nothing about which library is open."""
        p = self._prefs()
        p.test_dir = "/tmp/amaze_probe"
        p.test_mode = True
        self.assertEqual(self.REAL_CACHE, p.cache_dir)

    def test_the_real_paths_survive_the_round_trip(self):
        """The one that would cost a real library if it broke."""
        p = self._prefs()
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

    def test_the_library_path_keeps_its_trailing_separator(self):
        """The connectors build `self._path + self._filename`, so a missing separator silently reads the wrong file."""
        p = self._prefs()
        p.test_dir = "/tmp/amaze_probe"
        p.test_mode = True
        self.assertTrue(p.dir.endswith("/"), p.dir)

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


class ARetiredKeyIsNotSTRIPPED(unittest.TestCase):
    """A key this build no longer reads survives a rewrite: dropping a preference is a code change, never a data change."""

    def test_an_unknown_key_survives_a_load_and_save(self):
        import json
        folder = tempfile.mkdtemp(prefix="amaze_prefs_retired_")
        self.addCleanup(shutil.rmtree, folder, True)
        settings = os.path.join(folder, "settings.json")
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump({"texture_force_iconvert": True,
                       "some_future_builds_key": [1, 2, 3],
                       "sidebar_counts": True}, handle)

        p = prefs_mod.Prefs()
        p.path = folder
        p.load()
        p.sidebar_counts = False  # change something this build OWNS, or a fixture read back unchanged cannot tell a preserving rewrite from no rewrite at all
        p.save()

        with open(settings, encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(
            False, written.get("sidebar_counts"),
            "settings.json was not rewritten at all, so nothing below "
            "is evidence about what a rewrite preserves")
        self.assertEqual(
            True, written.get("texture_force_iconvert"),
            "a retired key was stripped from settings.json - the other "
            "machine's build reads this file too")
        self.assertEqual(
            [1, 2, 3], written.get("some_future_builds_key"),
            "a key this build does not know was dropped")


class TheHomeLayoutsLiveInHostos(unittest.TestCase):

    def test_prefs_carries_no_os_path_convention(self):
        """No hardcoded OS path convention anywhere in the `prefs/` package - hostos owns those, and the subject is the LAYER, so this walks every file in it."""
        checked = []
        for name in sorted(os.listdir(os.path.join(PACKAGE, "prefs"))):
            if not name.endswith(".py"):
                continue
            checked.append(name)
            self.assertNotIn(
                "Users|home", source_of("prefs/" + name),
                "prefs/%s hardcodes the home-directory layouts again - "
                "they belong in hostos, which is where a fourth one "
                "gets added" % name)
        self.assertIn("prefs.py", checked)  # a walk that finds nothing passes silently, so name the files it MUST have seen
        self.assertIn("persistence.py", checked)

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

    def test_an_unrecognised_layout_is_left_alone(self):
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

        class Record:
            payload = {}
            title = "Red Brick"

        class Source(matx_sources.GPUOpenSource):
            def __init__(self):
                self.calls = 0

            def _packages(self, record):
                self.calls += 1
                return []

        source = Source()
        record = Record()
        source._resolved_packages(record)
        source._resolved_packages(record)
        self.assertEqual(
            2, source.calls,
            "a failed lookup was cached, so the retry never reached the "
            "network")
        self.assertNotIn(
            "_resolved", record.payload,
            "the failure was written onto the record")

    def test_a_successful_lookup_is_cached(self):
        from amaze.core import matx_sources

        class Record:
            payload = {}
            title = "Red Brick"

        class Source(matx_sources.GPUOpenSource):
            def __init__(self):
                self.calls = 0

            def _packages(self, record):
                self.calls += 1
                return [("2K", "id", "http://example/x.zip")]

        source = Source()
        record = Record()
        source._resolved_packages(record)
        source._resolved_packages(record)
        self.assertEqual(1, source.calls,
                         "a successful lookup is no longer cached")

    def test_the_archive_is_discarded_in_a_finally(self):
        """A failed extract must not leave the archive behind: `matx_import` reads a non-empty package folder as already downloaded."""
        tree = ast.parse(source_of("core/matx_sources.py"))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and node.finalbody:
                dumped = ast.dump(ast.Module(body=node.finalbody,
                                             type_ignores=[]))
                if "zip_path" in dumped:
                    found = True
        self.assertTrue(
            found,
            "the downloaded archive is not cleaned up in a finally, so "
            "a failed extract poisons the package folder permanently")


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

        record = self._record()
        produce, _note, error = matx_import._producer_for(
            record, DyingSource(), "2K", prefs)
        self.assertIsNone(produce)
        self.assertIn("connection dropped", error)
        dest = os.path.join(matx_import.matx_dir(prefs.dir),
                            matx_import.package_dirname(record))
        self.assertFalse(
            os.path.isdir(dest) and os.listdir(dest),
            "the dead fetch occupied the destination - every later "
            "import will reuse the torn package")

    def test_a_download_with_no_mtlx_leaves_no_destination(self):
        """A fetch that SUCCEEDS and carries no .mtlx must not take the destination either, or the reuse check refuses that record for good."""
        from amaze.core import matx_import
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)

        class NoMtlxSource:
            name = "stub"

            def fetch(self, record, resolution, dest_dir, progress=None):
                os.makedirs(dest_dir, exist_ok=True)
                with open(os.path.join(dest_dir, "wood_diffuse.png"),
                          "wb") as handle:
                    handle.write(b"PNG")
                return {"mtlx": None}

        record = self._record()
        produce, _note, error = matx_import._producer_for(
            record, NoMtlxSource(), "2K", prefs)
        self.assertIsNone(produce)
        self.assertIn("No .mtlx", error)
        dest = os.path.join(matx_import.matx_dir(prefs.dir),
                            matx_import.package_dirname(record))
        self.assertFalse(
            os.path.isdir(dest) and os.listdir(dest),
            "the incomplete package took the destination, so every "
            "later import of this material is refused until somebody "
            "deletes the folder by hand")

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

    def test_a_failed_reinstall_puts_it_back(self):
        """The function removes the user's gallery first, so every failure path has to put it back or they lose it for the session."""
        body = source_of("core/gallery_import.py")
        tree = ast.parse(body)
        lines = body.splitlines()
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == "entries_from_file":
                target = "\n".join(lines[node.lineno - 1:node.end_lineno])
        self.assertIsNotNone(target)
        before_finally = target[:target.index("finally:")]
        self.assertIn(
            "if was_installed:", before_finally,
            "the installGallery failure path does not put the user's "
            "gallery back, so a browse operation costs them that "
            "gallery for the rest of the Houdini session")
        self.assertGreaterEqual(
            before_finally.count("installGallery"), 2,
            "nothing re-installs it on the failure path")


class OneTooltipEngine(unittest.TestCase):

    def test_the_model_paths_use_the_measured_one(self):
        for rel in ("core/code_library.py", "core/gradient_library.py",
                    "core/matx_library.py"):
            self.assertNotIn(
                "helpers.tooltip_html", source_of(rel),
                "%s still routes its tooltips through the unmeasured "
                "engine" % rel)


class SettingsAreNotWrittenPerMouseMove(unittest.TestCase):

    def test_the_ram_slider_leaves_persistence_to_close(self):
        """`ClickSlider` fires valueChanged on every mouseMoveEvent, so a numeric row that saved per tick would fsync settings.json through the whole drag."""
        self.assertFalse(
            calls("dialogs/prefs_dialog.py", "set_ram_cache_mb", "save"),
            "the RAM Cache setter saves on every tick again")

    def test_close_still_persists(self):
        self.assertTrue(
            calls("dialogs/prefs_dialog.py", "closeEvent", "save"),
            "nothing persists the dialog's values any more")


class TheDebugSessionSurvivesAPathChange(unittest.TestCase):

    def test_a_new_path_gets_a_new_session(self):
        """configure() clears the session on a path change, so it has to establish a new one or `log-check.py` reads the new file as having none."""
        from amaze.core import debug

        folder = tempfile.mkdtemp(prefix="amaze_debug_session_")
        self.addCleanup(shutil.rmtree, folder, True)
        first = os.path.join(folder, "a.jsonl")
        second = os.path.join(folder, "b.jsonl")
        previous = debug.log_path() if hasattr(debug, "log_path") else None

        debug.configure(True, first)
        debug.event("test", "one")
        debug.configure(True, second)          # already on, new path
        debug.event("test", "two")
        try:
            with open(second, encoding="utf-8") as handle:
                body = handle.read()
        finally:
            debug.configure(False, previous) if previous else \
                debug.configure(False)
        self.assertIn(
            '"session"', body,
            "the new file has no session field at all")
        self.assertNotIn(
            '"session": ""', body,
            "records in the new file carry an EMPTY session id, so "
            "log-check.py shows the file as having zero sessions and "
            "prints none of its records")


class OneRuleForWhatBelongsInAFolder(unittest.TestCase):

    def test_matches_delegates_to_the_per_location_rule(self):
        """One rule for what belongs in a folder: the flat door delegates, so it cannot answer without the per-location override."""
        self.assertTrue(
            calls("core/file_library.py", "matches", "matches_in"),
            "FileFolders.matches carries a second body again")

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


class TheFileLoaderQueueDoesNotBusySpin(unittest.TestCase):

    def test_it_re_arms_on_a_frame_not_immediately(self):
        """The queue waits for a loader to FINISH, so a zero-delay re-arm spins the handler at full event-loop rate on the thread that paints."""
        body = source_of("core/thumbnails.py")
        tree = ast.parse(body)
        delays = []  # the RE-ARM only: the initial schedule is correct at zero, because it has nothing to wait for
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name == "_dispatch_files"):
                continue
            for branch in ast.walk(node):
                if not (isinstance(branch, ast.If)
                        and "FILE_LOADER_LIMIT" in ast.dump(branch.test)):
                    continue
                for call in ast.walk(branch):
                    if (isinstance(call, ast.Call)
                            and getattr(call.func, "attr", "") == "singleShot"
                            and call.args
                            and isinstance(call.args[0], ast.Constant)):
                        delays.append(call.args[0].value)
        self.assertTrue(delays, "the cap's re-arm is gone entirely")
        self.assertTrue(
            all(d > 0 for d in delays),
            "the file-loader queue re-arms with a zero delay, so it "
            "spins at full event-loop rate on the thread that paints: "
            "%s" % delays)


if __name__ == "__main__":
    unittest.main()
