"""Prefs, online sources, and the long tail.

BATCH 4, the last of the 65. Its shape is a THIRD thing again: most of
these are a rule the codebase already wrote down, applied everywhere
except one place.

  * `hostos.py`'s docstring forbids hardcoding an OS path convention
    anywhere else - and prefs.py carried three OSes' home layouts in a
    regex;
  * `_category_map` documents caching-only-on-success by name - and the
    resolution cache eighty lines below it cached failures;
  * `contained_join` is the containment helper, pinned both ways - and
    the download paths hand-rolled it twice and skipped it once;
  * load()'s own comment says values go through their validating
    SETTERS - and six keys did not;
  * research.md #278 says staging containers go in a disabler - and the
    online library import did not.

Several read the SOURCE, and by AST rather than by text: three checks
in this round passed on a DOCSTRING that mentioned the very thing the
code had stopped doing.
"""

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
from amaze.helpers import helpers, hostos, ui_helpers  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_of(relative):
    with open(os.path.join(PACKAGE, relative), encoding="utf-8") as handle:
        return handle.read()


def calls(relative, func_name, callee) -> bool:
    """Does `func_name` CALL `callee`? By AST, never by text.

    Three checks in this batch passed on prose: a docstring reading "NO
    save() here", a comment naming the helper it had stopped calling,
    and a module docstring still listing a function in the wrong tier.
    """
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
    """Three copies: the Filter menu's, the Preferences switches', and
    enable_renderer_on_add's if/elif chain. The SECTION list twelve
    lines from the second was already converted to all_sections() after
    a hardcoded copy left the HIP tab with no switch."""

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
        """load() returns at its FileNotFoundError branch before
        reaching the .get() defaults, so __init__'s values are what a
        new machine keeps - and refresh_data writes them out on the
        first save. They were all False against True/False/True/True."""
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
        """The user-visible half: all-off meant the Materials Filter
        menu offered only 'All' over a library full of Karma and
        Redshift."""
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

    #: Every key that has a validating setter, with a value that would
    #: break it. `null` is the shape a hand edit or a future build's
    #: type change produces, and it is what killed the gear button.
    POISON = {
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

        # And every value has to be USABLE, because Preferences does
        # arithmetic on them inside a slot where PySide swallows the
        # error - which is how the gear button silently stopped
        # opening Preferences at all.
        self.assertIsInstance(p.scroll_speed, float)
        round(p.scroll_speed * 100)
        self.assertIsInstance(p.ram_cache_mb, int)
        self.assertIsInstance(p.texture_parallel_conversions, int)
        self.assertIsInstance(p.karma_rendersamples, int)
        self.assertIn(p.view_mode, ("grid", "list"))
        self.assertTrue(p.accent_color)

    def test_load_assigns_through_the_setters(self):
        """Source pin: the values are clamped in the setters, and a
        raw assignment bypasses every one of them.

        Reads `prefs/persistence.py`, where `load()` has lived since
        2026-08-09. A source pin follows its SUBJECT, never a
        filename: left on `prefs.py` it would assert about a file that
        no longer holds the method, and would then pass or fail for
        reasons unconnected to the invariant it is named for.
        """
        body = ast.dump(ast.parse(source_of("prefs/persistence.py")))
        self.assertIn(
            "_through_setter", body,
            "load() assigns these keys raw again")


class ThePerUserBlocksRoundTripAndMerge(unittest.TestCase):
    """The users dimension of settings.json (ROADMAP line 22): per-UID
    blocks, carried empty until the flip commits move keys into them.
    Pinned now because the merge shape must exist BEFORE the first key
    moves - two panes of one session both write this file."""

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
        """load() may not raise, and refresh_data() rewrites the key
        from the attribute - so junk cannot ride the unknown-key
        courtesy back to disk forever."""
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
    """One switch, one folder: on, and the library reads
    `<folder>/lib/` and the cache `<folder>/cache/`.

    THE CONTRACT THAT MATTERS IS THE WAY BACK. The real library path
    and the real cache path must be untouched the whole time the
    switch is on, because they are the only route to the real library
    - a switch that wrote over them would be a one-way door.
    """

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
        """The File section's thumbnails are keyed by file path on
        disk, so they say nothing about which library is open. Moving
        them threw away 2496 texture and 503 geometry thumbnails on
        every switch and regenerated them, and protected nothing - a
        test session only adds images that are correct and reusable.
        """
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
        """Half-configured is the state between ticking the box and
        picking a folder. Answering `/lib/` there would point the
        library at the filesystem root."""
        p = self._prefs()
        p.test_mode = True
        self.assertEqual(self.REAL_LIB, p.dir)
        self.assertEqual(self.REAL_CACHE, p.cache_dir)

    def test_the_library_path_keeps_its_trailing_separator(self):
        """The connectors build `self._path + self._filename`, so a
        missing separator silently reads `libATlibrary.json`."""
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
        """Run twice, or run on a folder holding real saved test
        materials: the second pass must add nothing."""
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


class ARetiredKeyIsNotSTRIPPED(unittest.TestCase):
    """`texture_force_iconvert` was removed from this build on
    2026-08-03 - the Conversion Engine catches by itself the failure
    that toggle was the manual workaround for.

    The KEY stays in an existing settings.json. Two machines share
    these files, they are not versioned, and an older build reading
    one still wants its value - the same reason the retired section
    keys `texture`/`geometry`/`hip` are left alone. load() keeps every
    key it read and refresh_data only overwrites the ones this build
    owns, so a removal is a code change and never a data change."""

    def test_an_unknown_key_survives_a_load_and_save(self):
        import json
        folder = tempfile.mkdtemp(prefix="amaze_prefs_retired_")
        self.addCleanup(shutil.rmtree, folder, True)
        settings = os.path.join(folder, "settings.json")
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump({"texture_force_iconvert": True,
                       "some_future_builds_key": [1, 2, 3],
                       "ram_cache_mb": 128}, handle)

        p = prefs_mod.Prefs()
        p.path = folder
        p.load()
        # CHANGE SOMETHING THIS BUILD OWNS, so the file on disk must
        # actually have been REWRITTEN for the assertions below to
        # hold. Without this the test wrote a fixture, read it back
        # unchanged, and could not tell "the retired key survived a
        # rewrite" from "no rewrite ever happened" - proved 2026-08-03
        # by putting `return` at the top of save() and watching it stay
        # green.
        p.ram_cache_mb = 256
        p.save()

        with open(settings, encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(
            256, written.get("ram_cache_mb"),
            "settings.json was not rewritten at all, so nothing below "
            "is evidence about what a rewrite preserves")
        self.assertEqual(
            True, written.get("texture_force_iconvert"),
            "a retired key was stripped from settings.json - the other "
            "machine's build reads this file too")
        self.assertEqual(
            [1, 2, 3], written.get("some_future_builds_key"),
            "a key this build does not know was dropped")
        self.assertEqual(
            256, written.get("ram_cache_mb"),
            "the keys this build DOES own stopped saving")


class TheHomeLayoutsLiveInHostos(unittest.TestCase):

    def test_prefs_carries_no_os_path_convention(self):
        """hostos.py's docstring: 'Nothing else in the codebase may
        test sys.platform or hardcode an OS path convention; a new
        platform quirk gets a function here, not a branch at a call
        site.' prefs.py carried macOS, Linux and Windows home layouts
        in one regex.

        WALKS THE WHOLE `prefs/` PACKAGE, not one filename. The subject
        is the preferences LAYER; the package held exactly one file
        until 2026-08-09, so "no OS layout in prefs.py" and "no OS
        layout in the preferences layer" were the same sentence by
        accident rather than by design. `persistence.py` is the moment
        they stop being the same - and it is the half that carries the
        path encoding, so it is where a home-directory layout would
        actually be written.
        """
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
        # A walk that finds nothing passes silently, which is how a
        # guard becomes decoration: name the files it MUST have seen.
        self.assertIn("prefs.py", checked)
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
        """contained_join resolves REALPATHS, so a symlink planted
        under matX/<package>/ cannot be the hop out - which a normpath
        comparison cannot see. There were two copies and they had
        already drifted from each other."""
        body = source_of("core/matx_sources.py")
        self.assertNotIn(
            "os.path.normpath(os.path.join(dest_dir", body,
            "a download path is checked by normpath again")
        # BY AST, per target - counting occurrences passed with one
        # removed, because the file has six and the threshold was
        # three. The RGL one is the target that had no check at all.
        tree = ast.parse(body)
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
        """_packages swallows every per-package error and returns [],
        and an empty list is a PRESENT key - so one network blip made
        every later import report 'has no downloadable package'
        instantly, blaming the material rather than the network."""
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
        """A BadZipFile - which a captive portal's HTML body with a
        correct Content-Length produces - skipped the removal, and
        matx_import then read the non-empty folder as 'already
        downloaded' and refused every later import of that material."""
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
    """Six converters accept `target_input` and re-forward it to the
    texture samplers nested behind them - but the dispatcher passed it
    only to convert_texture_sampler ITSELF, so a base_color texture
    behind an RSColorCorrection, RSColorLayer, Fresnel, RSMathRange or
    RSRamp converted with role "data" and a Raw colour space: a colour
    map read as linear floats, silently desaturated, with a success
    report. The dispatcher hands the hint to every converter whose
    signature takes it."""

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
    """`source.fetch` used to write straight into matX/<package>, so a
    fetch dying part-way left a non-empty directory - and the reuse
    check reads a non-empty directory as "already downloaded": torn
    textures reused forever, or an import refused forever when the
    .mtlx never arrived. The fetch lands in a scratch sibling and is
    renamed over only on success, so an occupied destination IS a
    complete package."""

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
        """A fetch that SUCCEEDS and carries no .mtlx - a repackaged
        archive, or one whose only .mtlx sat at a member path the
        extractor refused.

        The rename is what makes an occupied destination MEAN a
        complete package, and it ran BEFORE the .mtlx check - so this
        took the destination anyway, and the reuse check at the top of
        the import then refused this record permanently, until the
        folder was deleted by hand."""
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
    """`next(iter({}.values()))` raises StopIteration, whose str() is
    EMPTY - so an asset shipping no .mtlx variant at all reported
    "Download failed: " with nothing after the colon, exactly the
    two-meanings-of-an-empty-message shape the surrounding comments
    were written to end."""

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
    """createNode and destroy BOTH land on the live stack, and one
    performUndo resurrects the node WITH its children (research.md ▸
    Undo; the mechanism is measured in test_thumbnail_paths) - so a
    single Ctrl+Z after a save, a gallery import or a Redshift
    conversion brought back a container holding a duplicate of the
    material just handled.

    The rule, read structurally: a container is STAGING when the same
    function creates it and destroys it in a `finally` - destroyed on
    EVERY path - and then both halves sit inside
    `hou.undos.disabler()`. A container destroyed only on a FAILURE
    branch (the restored COP companion, an import's fallback
    destination, /obj/Amaze's own setName rollback) is a RESULT with a
    rollback: the user may undo the result, so its create stays on the
    stack and this scan deliberately does not match it."""

    #: render/thumbs.py joined 2026-08-08 and was the blind spot that
    #: mattered: it holds more scene scaffolding than any file here,
    #: and an unguarded `net.createNode("copnet")` sat against a
    #: guarded destroy in the same function's finally - the exact pair
    #: this scan exists to catch, in the one staging-heavy file it did
    #: not read.
    FILES = ("core/matx_import.py", "core/gallery_import.py",
             "render/nodes.py", "render/material_converter.py",
             "core/library.py", "render/thumbs.py")

    def test_every_staging_pair_is_off_the_stack(self):
        offenders = []
        pairs = 0
        for rel in self.FILES:
            body = source_of(rel)
            tree = ast.parse(body)
            # A disabler guards its LEXICAL block (staged_asset wraps
            # its whole body in one), so this reads scope, never a
            # line window.
            guarded_ranges = [
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
                # EVERY create for a name, not the last one. One
                # variable assigned in two branches - `copnet` is
                # created as a `copnet` on H22 and a `cop2net` before
                # it - kept a single lineno, and ast.walk is
                # breadth-first, so which branch survived was not even
                # source order. A guarded sibling then vouched for an
                # unguarded create: measured 2026-08-08, sabotaging the
                # legacy branch left this scan green.
                creates = {}
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
        """The function removes the gallery first to make the append
        position deterministic. When the reinstall then fails, the
        early return skipped the restoring finally - and that finally
        only covers the case where it ADDED one."""
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

    def test_the_old_engine_delegates(self):
        """Two engines solved the same problem by two rules, and the
        measured device-pixel fix landed in only one - so a tooltip
        wide in PIXELS but short in characters still crossed the
        screen through the other door."""
        self.assertFalse(
            calls("helpers/helpers.py", "tooltip_html", "escape"),
            "tooltip_html builds its own HTML again instead of "
            "delegating to the measured engine")
        self.assertTrue(
            calls("helpers/helpers.py", "tooltip_html", "tooltip_text"),
            "tooltip_html no longer delegates")

    def test_both_doors_answer_the_same(self):
        text = "A description that is short in characters but wide"
        self.assertEqual(helpers.tooltip_html(text),
                         ui_helpers.tooltip_text(text))

    def test_the_model_paths_use_the_measured_one(self):
        for rel in ("core/code_library.py", "core/gradient_library.py",
                    "core/matx_library.py"):
            self.assertNotIn(
                "helpers.tooltip_html", source_of(rel),
                "%s still routes its tooltips through the unmeasured "
                "engine" % rel)


class SettingsAreNotWrittenPerMouseMove(unittest.TestCase):

    def test_the_ram_slider_leaves_persistence_to_close(self):
        """ClickSlider fires valueChanged on every mouseMoveEvent, so
        one drag rewrote and FSYNCED settings.json dozens of times,
        each write also re-reading the file for the history snapshot.
        Every other numeric row in the dialog leaves it to closeEvent."""
        self.assertFalse(
            calls("dialogs/prefs_dialog.py", "set_ram_cache_mb", "save"),
            "the RAM Cache setter saves on every tick again")

    def test_close_still_persists(self):
        self.assertTrue(
            calls("dialogs/prefs_dialog.py", "closeEvent", "save"),
            "nothing persists the dialog's values any more")


class TheDebugSessionSurvivesAPathChange(unittest.TestCase):

    def test_a_new_path_gets_a_new_session(self):
        """configure() clears _session on a path change deliberately -
        and then only re-established it on the off->on edge, so every
        record in the new file carried an empty session id and
        log-check.py reported the file as having zero sessions."""
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
        """FileFolders.matches() was unreachable AND carried the global
        Show Unknown Files preference that the per-location override
        replaced - so the next consumer of the documented contract
        would have got the pre-2026-08-01 answer, and the sidebar
        number would disagree with the tiles."""
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
        """A zero-delay timer re-ran the handler on every event-loop
        turn - rebuilding the whole queue list each time - while the
        thing it waits for is a loader FINISHING, several seconds away
        on a network mount."""
        body = source_of("core/thumbnails.py")
        tree = ast.parse(body)
        # The RE-ARM only. The other singleShot(0, _dispatch_files) is
        # the initial schedule, which is correct at zero: it means
        # "dispatch on the next turn", and there is nothing to wait
        # for. My first version counted both and demanded the initial
        # schedule be delayed too.
        delays = []
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
