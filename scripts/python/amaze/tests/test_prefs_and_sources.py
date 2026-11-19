"""Prefs, online sources and other small checks; several read the source by AST, not by text."""

import ast
import builtins
import contextlib
import importlib.util
import json
import ntpath
import os
import shutil
import ssl
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
source_of = test_support.source_of


def calls(relative, func_name, callee) -> bool:
    """Does `func_name` call `callee`? By AST: a comment naming a helper is not a call to it."""
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

    def test_no_other_module_names_a_renderer_preference(self):
        """A switch or sample count named outside the table defines a renderer in a second place."""
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
        self.assertEqual([], spelled, "a renderer preference name is written outside core/renderers.py")


class RendererDefaultsAgree(unittest.TestCase):

    def test_an_empty_directory_loads_the_documented_defaults(self):
        """With no settings file load() returns early, so the __init__ values are what is kept."""
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
        """A new machine's Materials Filter menu offers the renderers, not just `All`."""
        empty = tempfile.mkdtemp(prefix="amaze_prefs_menu_")
        self.addCleanup(shutil.rmtree, empty, True)
        p = prefs_mod.Prefs()
        p.path = empty
        p.load()
        offered = [renderer.key for renderer in renderers.offered(p)]
        self.assertIn("Karma", offered)
        self.assertIn("Redshift", offered)


class SharedDefaultsAreInOneTable(unittest.TestCase):
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
                             "%s: __init__ differs from the table" % stored)

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
        """Adopting rejected a non-string for these; load() accepted it, and paths were built from it."""
        p = prefs_mod.Prefs()
        p.path = self._settings(
            {"shared_settings": {"img_dir": 5, "extension": None}})
        p.load()
        self.assertEqual(("img/", ".mat"), (p.img_dir, p.ext),
                         "a junk folder-layout value loaded raw")

    def test_a_library_folder_saved_without_its_slash_loads_with_it(self):
        """A folder without its slash, joined to file names, gives `libraryDataBase.json`."""
        library = tempfile.mkdtemp(prefix="amaze_no_slash_").replace("\\", "/")
        self.addCleanup(shutil.rmtree, library, True)
        p = prefs_mod.Prefs()
        p.path = self._settings({"directory": library.rstrip("/")})
        p.load()
        self.assertEqual(library.rstrip("/") + "/DataBase.json", p.dir + "DataBase.json")

    def test_load_clamps_parallel_downloads_as_the_setter_does(self):
        p = prefs_mod.Prefs()
        p.path = self._settings(
            {"shared_settings": {"matx_parallel_downloads": 64}})
        p.load()
        self.assertEqual(16, p.matx_parallel_downloads,
                         "load() skipped the setter's 1-16 clamp")


class LoadNeverRaisesAndAlwaysValidates(unittest.TestCase):

    POISON = {  # every key with a validating setter, against the value that breaks it
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

    def _write_invalid_settings(self, folder, **extra):
        import json
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(dict(self.POISON, **extra), handle)

    def test_an_invalid_settings_file_still_loads(self):
        folder = tempfile.mkdtemp(prefix="amaze_prefs_poison_")
        self.addCleanup(shutil.rmtree, folder, True)
        self._write_invalid_settings(folder)

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

    def test_preferences_opens_over_an_invalid_settings_file(self):
        """The Render rows pass these straight to spin boxes, which raise on anything but a number."""
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        self._write_invalid_settings(p.path, directory=p.dir,
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
                                  ("render_on_import", 7, 1),
                                  ("obj_drag_outline", "0", 0),
                                  ("obj_drag_outline", 7, 1)):
            with self.subTest(setting=name, value=given):
                setattr(p, name, given)
                self.assertEqual(kept, getattr(p, name))
        for name in ("rendersize", "rendersamples", "render_on_import",
                     "obj_drag_outline"):
            with self.subTest(setting=name, value=None):
                with self.assertRaises((TypeError, ValueError)):
                    setattr(p, name, None)    # the raise is what makes load() keep the default

    def test_every_spin_row_offers_what_its_setter_keeps(self):
        """A value past a row's end is clamped to that end, so the row can always show what is stored."""
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
                                     "the setter stores a value its row "
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
    """Per-UID blocks in settings.json, and the save-time merge of two panes in one session."""

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

    def test_blocks_are_kept_through_a_load_save_round_trip(self):
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

    def test_junk_shapes_load_without_raising_and_are_dropped_on_save(self):
        """load() may not raise, and refresh_data() rewrites the key from the attribute, dropping junk."""
        for junk in (5, "x", [1], {"a-uid": "not-a-dict"},
                     {"a-uid": None}):
            with self.subTest(users=junk):
                folder = self._folder()
                self._write(folder, {"users": junk})
                p = self._prefs_at(folder)
                p.load()
                p.save()
                self.assertEqual({}, self._read(folder)["users"])

    def test_a_uid_this_pane_lacks_is_merged_whole(self):
        folder = self._folder()
        self._write(folder, {})
        p = self._prefs_at(folder)
        p.load()
        p._users_blocks["aa11"] = {"thumbsize": 64}
        # Another pane saved after this one loaded, with its own user's block.
        self._write(folder, {"users": {"bb22": {"view_mode": "list"}}})
        p.save()
        raw = self._read(folder)["users"]
        self.assertEqual({"thumbsize": 64}, raw["aa11"],
                         "the merge dropped this pane's block")
        self.assertEqual({"view_mode": "list"}, raw["bb22"],
                         "the other pane's user was dropped")

    def test_inside_a_shared_uid_this_panes_value_is_kept_per_key(self):
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
                         "the other pane's value replaced this pane's value")
        self.assertEqual("list", raw["view_mode"],
                         "a key only the other pane had was dropped")


class ALibrarySwitchInOnePaneIsKept(unittest.TestCase):
    """r6: each pane has its own Prefs on one settings.json; B's saves keep A's library switch."""

    def test_the_other_panes_second_save_keeps_the_switch(self):
        import json
        config = tempfile.mkdtemp(prefix="amaze_two_panes_")
        self.addCleanup(shutil.rmtree, config, True)
        first, second = test_support.fresh_library(self), test_support.fresh_library(self)

        def pane():
            held = prefs_mod.Prefs()
            held.path = config
            held.load()
            return held

        start = prefs_mod.Prefs()
        start.path = config
        start.dir = first
        start.save()
        a, b = pane(), pane()
        a.dir = second    # Preferences in pane A switches the library
        a.save()
        b.sidebar_width = 300    # pane B drags its sidebar, twice
        b.save()
        b.sidebar_width = 310
        b.save()
        with open(os.path.join(config, "settings.json"), encoding="utf-8") as handle:
            stored = json.load(handle)["directory"]
        self.assertEqual(os.path.normpath(second),
                         os.path.normpath(hostos.expand_storage_path(stored)),
                         "pane B wrote the previous library back: the next Houdini opens it")
        self.assertEqual(second, b.dir, "pane B still points at the previous library")


class TheLibraryIsTheOneTheSettingsName(unittest.TestCase):
    """There is no second library beside the configured one; no code reads the old Test Library keys."""

    def test_prefs_have_no_test_library(self):
        p = prefs_mod.Prefs()
        for gone in ("test_mode", "test_dir", "real_dir"):
            self.assertFalse(hasattr(p, gone), gone)
        for gone in ("test_library_dir", "seed_test_folder", "TEST_LIB_SUBDIR"):
            self.assertFalse(hasattr(prefs_mod, gone), gone)

    def test_settings_that_still_hold_the_old_keys_open_the_configured_library(self):
        root = tempfile.mkdtemp(prefix="amaze_old_keys_")
        self.addCleanup(shutil.rmtree, root, True)
        real, other, settings = (os.path.join(root, name) for name in ("real", "other", "cfg"))
        for folder in (real, os.path.join(other, "lib"), settings):
            os.makedirs(folder)
        prefs_mod.create_library(real)
        prefs_mod.create_library(os.path.join(other, "lib"))
        p = prefs_mod.Prefs()
        p.path = settings
        p.dir = real
        p.save()
        path = os.path.join(settings, "settings.json")
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertNotIn("test_mode", document)
        self.assertNotIn("test_dir", document)
        document.update(test_mode=True, test_dir=other)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        fresh = prefs_mod.Prefs()
        fresh.path = settings
        self.assertTrue(fresh.load())
        self.assertEqual(os.path.normpath(real), os.path.normpath(fresh.dir))

    def test_the_saved_directory_is_normalised_by_one_helper(self):
        """The saved `directory` is normalised by one helper, `_normalised_dir`."""
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
            self.assertEqual(shaped, p.dir, "the saved `directory` was normalised differently")


class TheHomeLayoutsAreInHostos(unittest.TestCase):

    def test_rehome_rewrites_only_when_the_result_exists(self):
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        self.assertEqual(
            "/Users/someone-else/definitely/not/here",
            hostos.rehome("/Users/someone-else/definitely/not/here"),
            "rehome rewrote a path whose target does not exist - the "
            "existence check is the only thing stopping a shared "
            "/home/projects mount being rewritten into this user's home")
        # And it does rewrite a path that exists.
        self.assertEqual(
            home + "/", hostos.rehome("/Users/someone-else/"))
        self.assertEqual(
            "D:/Profiles/someone/lib",
            hostos.rehome("D:/Profiles/someone/lib"),
            "a redirected Windows profile was rewritten - it is not a "
            "recognised layout and must be left as it is")


class ContainmentMatchesRealpath(unittest.TestCase):
    """`contained_join` resolves the base once and calls realpath only where a link could redirect."""

    @staticmethod
    def _by_realpath(base, *parts):
        """The result every caller relied on: both paths resolved by `os.path.realpath`."""
        composed = os.path.join(base, *parts)
        real_base, real = os.path.realpath(base), os.path.realpath(composed)
        if real != real_base and not real.startswith(real_base.rstrip(os.sep) + os.sep):
            raise hostos.PathOutsideBase(composed)
        return composed

    def setUp(self):
        self.base = os.path.join(tempfile.mkdtemp(prefix="amaze_contain_"), "lib")
        self.outside = tempfile.mkdtemp(prefix="amaze_outside_")
        for folder in (os.path.dirname(self.base), self.outside):
            self.addCleanup(shutil.rmtree, folder, True)
        os.makedirs(os.path.join(self.base, "mat"))
        for path in (os.path.join(self.base, "mat", "a.mat"), os.path.join(self.outside, "o.mat")):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")
        os.symlink(self.outside, os.path.join(self.base, "mat", "away"))
        os.symlink(os.path.join(self.outside, "o.mat"), os.path.join(self.base, "mat", "o.mat"))
        os.symlink(os.path.join(self.base, "mat", "a.mat"), os.path.join(self.base, "mat", "in.mat"))

    def test_every_path_form_gets_the_result_realpath_gives(self):
        shapes = [("mat", "a.mat"), ("mat/a.mat",), ("mat", "missing.mat"), ("new", "deeper", "x.mat"),
                  ("mat", "in.mat"), ("mat", "o.mat"), ("mat", "away", "o.mat"), ("mat", "away"),
                  ("mat/", "a.mat"), ("mat", "..", "..", "x.mat"), ("mat", "..", "mat", "a.mat"),
                  ("mat", "."), ("",), (self.outside, "o.mat"), (os.path.join(self.base, "mat"),)]
        refused = 0
        for parts in shapes:
            with self.subTest(parts=parts):
                try:
                    expected = self._by_realpath(self.base, *parts)
                except hostos.PathOutsideBase:
                    refused += 1
                    with self.assertRaises(hostos.PathOutsideBase):
                        hostos.contained_join(self.base, *parts)
                    continue
                self.assertEqual(expected, hostos.contained_join(self.base, *parts))
        self.assertEqual(5, refused, "premise: the shapes no longer include five escapes")

    def test_a_plain_name_under_a_resolved_base_costs_no_realpath(self):
        hostos.contained_join(self.base, "mat", "a.mat")    # resolves the base, once
        with mock.patch.object(os.path, "realpath", wraps=os.path.realpath) as realpath:
            hostos.contained_join(self.base, "mat", "a.mat")
            hostos.contained_join(self.base, "mat", "missing.mat")
            self.assertEqual(0, realpath.call_count, "a plain name was resolved component by component")
            with self.assertRaises(hostos.PathOutsideBase):
                hostos.contained_join(self.base, "mat", "o.mat")
            self.assertEqual(1, realpath.call_count, "a link was not passed to realpath")


class OnlineDownloadsStayInsideTheLibrary(unittest.TestCase):

    def test_no_hand_rolled_containment_is_left(self):
        """`contained_join` resolves realpaths, so a planted symlink cannot lead outside."""
        body = source_of("core/matx_sources.py")
        self.assertNotIn(
            "os.path.normpath(os.path.join(dest_dir", body,
            "a download path is checked by normpath again")
        tree = ast.parse(body)  # by AST, per target: counting occurrences passed with one check removed
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

    def test_a_package_past_the_cap_raises_package_too_large_before_unpacking(self):
        import shutil
        import tempfile
        import zipfile
        from unittest import mock

        from amaze import messages
        from amaze.core import matx_sources, packages
        from amaze.helpers import wording
        dest = tempfile.mkdtemp(prefix="amaze_gpuopen_")
        self.addCleanup(shutil.rmtree, dest, True)

        def served(url, path, on_bytes=None, ceiling=None):
            with zipfile.ZipFile(path, "w") as bundle:
                bundle.writestr("brick/brick.mtlx", "<materialx/>")
                bundle.writestr("brick/brick_color.png", b"x" * 4000)
                bundle.writestr("../outside.txt", b"y")
            return path

        class Record:
            payload = {}
            title = "Red Brick"

        class Source(matx_sources.GPUOpenSource):
            def __init__(self):
                pass

            def _resolved_packages(self, record):
                return [("2K", "id", "https://example.invalid/brick.zip")]

        with mock.patch.object(matx_sources, "download", served), \
                mock.patch.object(matx_sources, "report_unsafe") as reported, \
                mock.patch.object(packages, "MAX_UNPACKED_BYTES", 1000), \
                self.assertRaises(OSError) as caught:
            Source().fetch(Record(), "2K", dest)
        self.assertEqual(messages.PACKAGE_TOO_LARGE % (wording.byte_size(4012),
                                                       wording.byte_size(1000)),
                         str(caught.exception))
        self.assertEqual([], os.listdir(dest), "a refused package still unpacked")
        reported.assert_not_called()    # its alert states the rest imported, which is false after a refusal

    def test_a_failed_package_lookup_is_not_cached(self):
        """`_packages` returns [] on error, a present key, so a cached [] would outlast a network error."""
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


class RefreshClearsEveryCacheASourceKeeps(unittest.TestCase):
    """Refresh drops every source cache, or the old site is served until restart."""

    def test_gpuopen_refresh_clears_the_category_map(self):
        from amaze.core import matx_sources
        source = matx_sources.GPUOpenSource()
        source._categories = {"1": "Metals"}
        source.refresh()
        self.assertIsNone(
            source._categories,
            "the category map was kept through Refresh - a renamed remote "
            "category lists its materials under Uncategorized until "
            "Houdini restarts")

    def test_every_source_with_hosted_pictures_clears_their_zip_offsets(self):
        """A picture's offset is read from the zip once; kept past Refresh it points into the old zip."""
        from amaze.core import matx_sources
        hosting = [cls for cls in matx_sources.SOURCES if cls.PREVIEWS]
        self.assertTrue(hosting, "no source hosts pictures, so this checks nothing")
        kept = []
        for cls in hosting:
            source = cls()
            source._previews = {"old.jpg": {"offset": 0, "size": 1, "crc": 0}}
            source.refresh()
            if source._previews is not None:
                kept.append(cls.__name__)
        self.assertEqual([], kept, "these kept the old picture offsets through Refresh")


class TheShippedTableIsClosedAfterTheSizeCheck(unittest.TestCase):

    def test_usable_leaves_no_file_open(self):
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

    def test_a_source_that_fills_the_cap_is_logged(self):
        """No source fills the cap today; the log records when one starts to."""
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


class TheCatalogueCacheIsWrittenWhole(unittest.TestCase):
    """The on-disk Online catalogue is replaced whole or not at all."""

    def test_a_write_that_fails_part_way_keeps_the_last_catalogue(self):
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
                         "premise: the first catalogue was not saved")

        def write_part_then_fail(obj, handle, *args, **kwargs):
            handle.write('{"records": [{"sou')
            raise OSError(28, "No space left on device")

        with mock.patch.object(json, "dump", write_part_then_fail):
            with test_support.captured_log():
                model._save_cache([matx_sources.MatxRecord(
                    source="GPUOpen", uid="x", title="X")])
        self.assertEqual(
            3, len(model._load_cache() or ()),
            "a write that failed part-way left a truncated catalogue, so the "
            "next Online open loses the whole cached list")


class ARemapOnAColourChainStillRemaps(unittest.TestCase):
    """With a color3 source mtlxremap/mtlxclamp use `_color3` parms: ranges go via `_set_poly_parm`."""

    def test_the_range_values_are_set_on_the_live_parm_variant(self):
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
                         "premise: wiring the color3 image changed the "
                         "remap's signature")
        self.assertEqual(
            (0.25, 0.25, 0.25), tuple(remap.parmTuple("inlow_color3").eval()),
            "old_min was not set on the LIVE inlow variant - the remap "
            "renders with its identity defaults")
        self.assertEqual("mtlxclamp", out.type().name(),
                         "premise: clamp on appends an mtlxclamp")
        self.assertEqual(
            (0.1, 0.1, 0.1), tuple(out.parmTuple("low_color3").eval()),
            "new_min was not set on the clamp's LIVE low variant")


class VendorTransformsRunOnlyInTheOpenPBRConverter(unittest.TestCase):
    """The fuzz^2.5 curve and coat-roughness mix are OpenPBR-only; elsewhere they corrupt 1:1 values."""

    def test_only_the_openpbr_converter_runs_them(self):
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
                             "`convert_openpbr_material` no longer runs its transforms")


class ConvertNodePassesTheTargetInput(unittest.TestCase):
    """`target_input` is passed to every converter taking it, so a nested texture keeps its role."""

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
            "forwards it - the nested texture is treated as data/Raw")
        self.assertTrue(received.get("bare"),
                        "a converter without the parameter broke")


class AHalfFetchedPackageIsNotReused(unittest.TestCase):
    """The fetch is renamed into place only on success, so an existing destination is complete."""

    def _record(self):
        class Record:
            kind = "package"
            uid = "seam1"
            title = "Seam Test"
            source = "stub"
            payload = {}

        return Record()

    def test_a_fetch_that_fails_leaves_no_destination(self):
        from amaze.core import matx_import
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)

        class FailingSource:
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

        for source, why in ((FailingSource(), "connection dropped"),
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
                    "a failed or .mtlx-less fetch left files at the destination - "
                    "every later import reuses or rejects it")

    def test_the_retry_fetches_fresh_and_is_complete(self):
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
            "the completed fetch was never moved to the destination")
        self.assertFalse(
            os.path.isdir(dest + ".downloading"),
            "the `.downloading` folder remains after a successful fetch")


class ANoVariantAssetRaisesWithItsName(unittest.TestCase):
    """`StopIteration` has an empty str(), so a fetch with no .mtlx variant names the asset."""

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
    """Staging containers are made and destroyed under `hou.undos.disabler()`. ▸r/undo-groups"""

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
                creates = {}  # every create for a name, not the last, so one guarded create cannot cover another
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
            pairs, 7,
            "the scan matched %d staging pairs where the source has "
            "seven - it finds too few, so passing proves nothing" % pairs)
        self.assertEqual(
            [], offenders,
            "these put half of a staging pair on the LIVE undo stack, "
            "so one Ctrl+Z recreates the container with its "
            "children: %s" % offenders)


class AGalleryIsLeftAsItWasFound(unittest.TestCase):

    def test_OperationFailed_really_is_covered_by_hou_Error(self):
        """The narrowed except clause relies on this subclassing. ▸r/gallery-entries"""
        self.assertTrue(
            issubclass(hou.OperationFailed, hou.Error),
            "hou.OperationFailed is no longer a hou.Error, so the "
            "removeGallery clause silently stopped catching it")


class SettingsAreNotWrittenPerMouseMove(unittest.TestCase):

    def test_close_still_persists(self):
        self.assertTrue(
            calls("dialogs/prefs_dialog.py", "closeEvent", "save"),
            "nothing saves the dialog's values any more")

    def test_the_ram_slider_leaves_persistence_to_close(self):
        """ClickSlider emits on every mouse move, so saving per tick fsyncs settings.json all drag long."""
        self.assertFalse(
            calls("dialogs/prefs_dialog.py", "set_ram_cache_mb", "save"),
            "the RAM Cache setter saves on every tick again")


class TheFileLoaderQueueDoesNotBusySpin(unittest.TestCase):

    def test_it_reschedules_after_a_frame_not_immediately(self):
        """A zero-delay re-arm runs the handler at full event-loop rate on the painting thread."""
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

    def test_matches_in_and_matches_agree(self):
        class Prefs:
            file_show_unknown = False

        model = file_library.FileFolders.__new__(file_library.FileFolders)
        model.preferences = Prefs()
        for name in ("thing.png", "thing.bgeo.sc", "thing.hip",
                     "thing.wat", ".hidden"):
            self.assertEqual(
                model.matches_in("", name), model.matches(name),
                "the flat and per-location answers disagree for %r"
                % name)


class TheOsHandOffsNeverRaise(unittest.TestCase):
    """The log buttons call these without a try: a failing or missing handler is caught inside."""

    def test_no_platform_branch_raises_when_every_handler_fails(self):
        def missing_program(*_args, **_kwargs):
            raise FileNotFoundError("no such program")

        for mac, windows in ((True, False), (False, True), (False, False)):
            with self.subTest(macos=mac, windows=windows), \
                    mock.patch.object(hostos, "is_macos",
                                      return_value=mac), \
                    mock.patch.object(hostos, "is_windows",
                                      return_value=windows), \
                    mock.patch.object(hostos.subprocess, "call",
                                      side_effect=missing_program), \
                    mock.patch.object(hostos.os, "startfile", create=True,
                                      side_effect=OSError("no app")):
                hostos.open_path("/nowhere/amaze_debug.jsonl")
                hostos.reveal_path("/nowhere/amaze_debug.jsonl")


class RevealUsesHoudinisRevealFile(unittest.TestCase):
    """`ui_helpers.reveal` calls `fileutils.revealFile`, which Houdini ships, on every system."""

    def setUp(self):
        self.ran, self.revealed = [], []
        patcher = mock.patch.object(hostos, "reveal_path", self.revealed.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="amaze_reveal_"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def _commands(self, system):
        """Houdini's `fileutils` as it runs on `system`, its commands recorded and not run."""
        import fileutils
        return mock.patch.multiple(
            fileutils,
            subprocess=types.SimpleNamespace(call=self.ran.append),
            platform=types.SimpleNamespace(system=lambda: system))

    def test_a_file_or_a_folder_is_shown_with_houdinis_command_for_each_system(self):
        from amaze.helpers import ui_helpers
        target = os.path.join(self.folder, "amaze_debug.jsonl")
        parent = os.path.dirname(self.folder)
        for system, expected in (
                ("Darwin", [["open", "-R", target], ["open", "-R", self.folder]]),
                ("Windows", [["explorer", "/select,", target],
                             ["explorer", "/select,", self.folder]]),
                ("Linux", [["xdg-open", self.folder], ["xdg-open", parent]])):
            with self.subTest(system=system), self._commands(system):
                del self.ran[:]
                ui_helpers.reveal(target)
                ui_helpers.reveal(self.folder + "/")
                self.assertEqual(expected, self.ran)
        self.assertEqual([], self.revealed, "Amaze's own reveal_path ran beside Houdini's")

    def test_when_houdinis_function_raises_nothing_else_is_run(self):
        from amaze.helpers import ui_helpers
        import fileutils
        with mock.patch.object(fileutils, "revealFile", side_effect=OSError("no open")):
            ui_helpers.reveal(self.folder)
        self.assertEqual([], self.revealed)

    def test_every_caller_inside_houdini_uses_houdinis_file_browser(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        callers = []
        for folder in ("panel", "dialogs", "actions", "utils", "core", "render"):
            for dirpath, _dirs, files in os.walk(os.path.join(root, folder)):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as handle:
                        tree = ast.parse(handle.read())
                    callers += ["%s:%d" % (os.path.relpath(path, root), node.lineno)
                                for node in ast.walk(tree)
                                if isinstance(node, ast.Attribute) and node.attr == "reveal_path"]
        self.assertEqual([], callers, "these call `reveal_path` instead of Houdini's file browser")

class TheUserRowCreatesAndDeletes(unittest.TestCase):
    """Preferences > User creates, renames and deletes; deleting removes all tagged theirs."""

    def test_the_user_row_offers_create_and_delete(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog, user_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.library_user = users.create(p, "Cobalt")
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combo = dlg.cbb_library_user
        sentinel = user_dialog.CREATE
        rows = [combo.itemData(i) for i in range(combo.count())]
        self.assertIn(sentinel, rows,
                      "the row cannot create a user - the create entry "
                      "is missing here")
        self.assertEqual(sentinel, rows[-1],
                         "the create entry is not the LAST row, so it "
                         "reads as a user called Create")
        self.assertTrue(dlg._btn_delete_user.isEnabled())

    def test_the_users_are_listed_a_to_z(self):
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        for name in ("sienna", "Cobalt", "Fern"):
            p.library_user = users.create(p, name)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        combo = dlg.cbb_library_user
        self.assertEqual(["Cobalt", "Fern", "sienna"],
                         [combo.itemText(i) for i in range(combo.count() - 1)],
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
                        "`_show_quietly` unblocked signals the caller had blocked")

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

    def test_deleting_the_current_user_selects_nobody(self):
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
                         "Apply is enabled with no user picked")

    def test_the_only_user_left_is_listed_and_not_picked(self):
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
        self.assertGreaterEqual(dlg.cbb_library_user.findText("Sienna"), 0)
        self.assertEqual(-1, dlg.cbb_library_user.currentIndex(),
                         "the user left was picked because it was the only one")
        self.assertEqual("", str(p.library_user or ""))


class TheOverwriteSwitchFollowsTheLibrary(unittest.TestCase):
    """A library switch under the open dialog re-reads the overwrite policy for the new library."""

    def test_switching_libraries_rereads_the_overwrite_policy(self):
        from amaze.core import library_settings
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        library_settings.set_allow_overwrite(p, False)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg._cbx_allow_overwrite.isChecked(),
                         "premise: the first library forbids overwrite")
        folder = test_support.scratch_dir("amaze_policy_switch_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.assertTrue(prefs_mod.create_library(folder), "premise: the other library is made")
        dlg._switch_library(folder, p.library_user)
        self.assertTrue(
            dlg._cbx_allow_overwrite.isChecked(),
            "the switch still shows the PREVIOUS library's policy - a "
            "library with no policy.json allows overwrite")


class TheCacheWipeCannotBeSuppressed(unittest.TestCase):
    """`displayConfirmation` defaults `suppress` to the global OverwriteFile do-not-ask flag."""

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
        self.assertIn("kwargs", seen, "the wipe never showed a confirmation")
        self.assertEqual(messages.CONFIRM_CLEAR_THUMBNAIL_CACHE,
                         seen.get("text"))
        self.assertEqual(
            hou.confirmType.NoConfirmType, seen["kwargs"].get("suppress"),
            "the cache wipe uses a SUPPRESSABLE confirmation: with "
            "`suppress` at its default of `hou.confirmType.OverwriteFile`, "
            "one tick of do-not-ask-again anywhere in Houdini deletes every "
            "cached thumbnail with no question asked")


class PreferencesShowTheDrawnTexts(unittest.TestCase):
    """Three Preferences messages use the designed wording in `messages.py`, not an inline copy."""

    def _dialog(self):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_the_material_versions_help(self):
        from amaze import messages
        from amaze.core import library_settings
        dlg = self._dialog()
        library_settings.set_allow_overwrite(dlg._prefs, False)
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

    def _save_log(self, answer=1, **patches):
        """Save Log via hou.ui, as in all of Preferences: (folder, export, messages, reveal)."""
        from amaze.core import debug
        from amaze.tests import test_support
        dlg = self._dialog()
        folder = test_support.scratch_dir("amaze_log_save_")
        self.addCleanup(shutil.rmtree, folder, True)
        asked, displayed = [], []

        def display(text, *_args, **kwargs):
            displayed.append(dict(kwargs, text=text))
            return answer

        ui = types.SimpleNamespace(
            selectFile=lambda *a, **k: asked.append(k) or folder + "/", displayMessage=display)
        with mock.patch.object(hou, "ui", ui, create=True), \
                mock.patch.object(QtWidgets.QFileDialog, "getExistingDirectory",
                                  side_effect=AssertionError("a Qt picker")), \
                mock.patch.object(QtWidgets.QMessageBox, "exec",
                                  side_effect=AssertionError("a Qt box")), \
                mock.patch.object(debug, "export_log", **patches) as export, \
                mock.patch("amaze.helpers.ui_helpers.reveal") as reveal:
            dlg.save_debug_log()
        self.assertEqual([hou.fileType.Directory], [k.get("file_type") for k in asked])
        return folder, export, displayed, reveal

    def test_the_log_save_failure(self):
        from amaze import messages
        failure = OSError("the disk is full")
        _folder, _export, displayed, _reveal = self._save_log(side_effect=failure)
        self.assertEqual([(messages.LOG_NOT_SAVED_UNEXPECTED % failure, messages.TITLE_LOG_NOT_SAVED,
                           hou.severityType.Warning)],
                         [(s["text"], s.get("title"), s.get("severity")) for s in displayed])

    def test_an_export_refused_log_save_shows_the_reason(self):
        from amaze import messages
        from amaze.core import debug
        _folder, _export, displayed, _reveal = self._save_log(
            side_effect=debug.ExportRefused("the log is empty"))
        self.assertEqual([("the log is empty", messages.TITLE_LOG_NOT_SAVED,
                           hou.severityType.Warning)],
                         [(s["text"], s.get("title"), s.get("severity")) for s in displayed])

    def test_a_saved_log_offers_show_in_folder(self):
        from amaze import messages
        target = os.path.join("/somewhere", "amaze_debug.jsonl")
        for answer, revealed in ((0, [target]), (1, [])):
            with self.subTest(answer=answer):
                folder, export, displayed, reveal = self._save_log(answer=answer, return_value=target)
                self.assertEqual(os.path.normpath(folder),
                                 os.path.normpath(export.call_args.args[0]))
                shown, = displayed
                self.assertEqual(messages.LOG_SAVED_AS % "amaze_debug.jsonl", shown["text"])
                self.assertEqual(messages.HELP_LOG_SAVED, shown.get("help"))
                self.assertEqual(messages.TITLE_LOG_SAVED, shown.get("title"))
                self.assertEqual(messages.BUTTON_SHOW_IN_FOLDER, shown["buttons"][0])
                self.assertEqual(revealed, [c.args[0] for c in reveal.call_args_list])

    def test_the_two_log_titles_are_spelled_as_one_pair(self):
        from amaze import messages
        self.assertEqual(("Log not saved", "Log saved"),
                         (messages.TITLE_LOG_NOT_SAVED, messages.TITLE_LOG_SAVED))

class ThePresetThemeIsFollowed(unittest.TestCase):
    """A named theme leaves `themeValues` empty; its triplets come from the theme files. ▸r/pluto-theme"""

    def setUp(self):
        from amaze.helpers import theme
        self.theme = theme
        theme._read.cache_clear()
        self.addCleanup(theme._read.cache_clear)
        self.prefs = {}
        self.folder = tempfile.mkdtemp(prefix="amaze_themes_")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        shipped = hou.text.expandString("$HFS/houdini/config/Themes")
        for patcher in (
                mock.patch.object(hou, "getPreference",
                                  lambda name: self.prefs.get(name, "")),
                mock.patch.object(hou, "findDirectories",
                                  lambda path: (self.folder, shipped))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _base(self, triplet):
        from hutil import oklch
        return self.theme._to_qcolor(oklch, triplet).name()

    def _read_base(self):
        read = self.theme._read()
        return None if read is None else read["base"].name()

    def test_a_stock_preset_is_read_by_name(self):
        self.prefs["pluto_ui.themeName"] = "Default Colorful"
        self.assertEqual(self._base([280, 5, 18]), self._read_base())

    def test_hand_edited_values_take_precedence_over_the_name(self):
        self.prefs.update({"pluto_ui.themeName": "Default Colorful",
                           "pluto_ui.themeValues": json.dumps(
                               {"base": [100, 10, 20], "primary": [270, 29, 55],
                                "highlight": [82, 60, 80]})})
        self.assertEqual(self._base([100, 10, 20]), self._read_base())

    def test_a_user_theme_is_read_by_its_file_and_name(self):
        path = os.path.join(self.folder, "mine.theme.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"name": "Mine", "theme": {"base": [30, 8, 22], "primary": [270, 29, 55],
                                                 "highlight": [82, 60, 80]}}, handle)
        self.prefs["pluto_ui.themeName"] = path.replace("\\", "/") + "::Mine"
        self.assertEqual(self._base([30, 8, 22]), self._read_base())

    def test_an_unknown_name_falls_back_to_the_built_in_colors(self):
        self.prefs["pluto_ui.themeName"] = "No Such Theme"
        self.assertIsNone(self.theme._read())

class ThePickersStartInAForwardSlashPath(unittest.TestCase):
    """`hou.ui.selectFile` wants forward slashes in `start_directory`, even on Windows."""

    def _started_in(self, method):
        seen = {}

        def select_file(*_args, **kwargs):
            seen.update(kwargs)
            return ""   # Cancel, so the method returns before writing a preference

        # patching os.sep runs `hostos.canonical_path_key` through its Windows reading
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
        p.cache_dir = ""   # unset: falls through to the machine's convention, built by `os.path.join`
        dlg = self._dialog(p)
        from amaze.dialogs import prefs_dialog
        native = "C:\\scratch\\AppData\\Local\\Amaze\\Cache"
        with mock.patch.object(prefs_dialog.hostos, "cache_root",   # the dialog's own reference: a fixture panel reloads hostos
                               lambda: native):
            start = self._started_in(dlg.change_cache_path)
        self.assertEqual(
            "C:/scratch/AppData/Local/Amaze/Cache", start,
            "the cache picker opens on a native Windows path; selectFile "
            "requires forward slashes there and ignores the rest")


class APickedRootKeepsItsSlash(unittest.TestCase):
    """Only a trailing slash that is not the root is removed: `D:` means drive D's current folder."""

    WINDOWS_OS = types.SimpleNamespace(path=ntpath, sep="\\")    # what os.path and os.sep are there

    def _picked(self, method, answer, windows=False):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support
        p = test_support.fixture_prefs(self)
        p.cache_dir = "/start"    # so the picker does not ask for the machine's cache root
        dlg = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dlg.deleteLater)
        ui = types.SimpleNamespace(selectFile=lambda *_a, **_k: answer,
                                   displayMessage=lambda *_a, **_k: 0)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(hou, "ui", ui, create=True))
            stack.enter_context(mock.patch.object(p, "save", lambda: None))
            stack.enter_context(mock.patch.object(
                prefs_dialog.hostos, "set_cache_override", lambda _path: None))
            if windows:
                stack.enter_context(mock.patch.object(
                    prefs_dialog.hostos, "os", self.WINDOWS_OS))
            getattr(dlg, method)()
        return p.cache_dir

    def test_a_picked_root_is_kept_whole(self):
        for method in ("change_cache_path",):
            for answer, windows, kept in (
                    ("/", False, "/"), ("D:/", True, "D:/"),
                    ("/Volumes/cache/", False, "/Volumes/cache"),
                    ("D:/shots/", True, "D:/shots")):
                with self.subTest(picker=method, picked=answer):
                    self.assertEqual(kept,
                                     self._picked(method, answer, windows))


class ALoadOnceResultIsKeptUntilCleared(unittest.TestCase):
    """Each cached result is computed on the first call and kept until `cache_clear()`."""

    def _fresh(self, cached):
        """Empties `cached` now and after the test; with no cache to empty, the count fails."""
        clear = getattr(cached, "cache_clear", lambda: None)
        clear()
        self.addCleanup(clear)

    def _scratch(self):
        """A folder of this test's own, removed after it."""
        folder = test_support.scratch_dir("amaze_load_once_")
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def _hh(self, env):
        """Patches `hou.getenv` to read `$HH` from `env`, so a test may set it part way."""
        real = hou.getenv

        def getenv(name, *rest, **named):
            return env["HH"] if name == "HH" else real(name, *rest, **named)
        return mock.patch.object(hou, "getenv", getenv)

    def _stub_hh(self):
        """A `$HH` whose `scripts/scene/lop_dragdrop.py` only sets `LOADED`."""
        folder = self._scratch()
        test_support.write_text(os.path.join(folder, "scripts", "scene", "lop_dragdrop.py"),
                                'LOADED = "stub"\n')
        return folder

    def _specs(self):
        """Counts the module specs built, one per load of `lop_dragdrop.py`."""
        return mock.patch.object(importlib.util, "spec_from_file_location",
                                 wraps=importlib.util.spec_from_file_location)

    def test_real_specs_read_the_spec_file_once(self):
        from amaze.render import generator
        self._fresh(generator.real_specs)
        path = os.path.join(self._scratch(), "material_specs.json")
        test_support.write_text(path, json.dumps({"entries": [{"spec": {}}]}))
        with mock.patch.object(generator, "_SPECS_FILE", path), \
                mock.patch.object(generator, "json", wraps=json) as parsed:
            first, second = generator.real_specs(), generator.real_specs()
            self.assertEqual([{"spec": {}}], first, "the specs read were not the scratch file")
            self.assertEqual(1, parsed.load.call_count, "a second call read the specs again")
            self.assertIs(first, second)
            generator.real_specs.cache_clear()
            generator.real_specs()
            self.assertEqual(2, parsed.load.call_count,
                             "after cache_clear() the next call did not read the specs")

    def test_online_facts_read_each_table_once(self):
        from amaze.render import generator
        self._fresh(generator.online_facts)
        folder = self._scratch()
        table = json.dumps({"materials": {"grey": {"color": [0.5, 0.5, 0.5]}}})
        for _source, filename in generator._ONLINE_TABLES:
            test_support.write_text(os.path.join(folder, filename), table)
        tables = len(generator._ONLINE_TABLES)
        with mock.patch.object(generator, "_RES_DIR", folder), \
                mock.patch.object(generator, "json", wraps=json) as parsed:
            first, second = generator.online_facts(), generator.online_facts()
            self.assertEqual(tables, len(first), "the tables read were not the scratch ones")
            self.assertEqual(tables, parsed.load.call_count, "a second call read the tables again")
            self.assertIs(first, second)
            generator.online_facts.cache_clear()
            generator.online_facts()
            self.assertEqual(2 * tables, parsed.load.call_count,
                             "after cache_clear() the next call did not read the tables")

    def test_character_rates_measure_the_specs_once(self):
        from amaze.render import generator
        self._fresh(generator.character_rates)
        entries = [{"spec": {"coat": 0.5}}, {"spec": {"coat": 0.0}}]
        with mock.patch.object(generator, "real_specs", return_value=entries) as specs:
            first, second = generator.character_rates(), generator.character_rates()
            self.assertEqual(0.5, first["coat"], "the rates were not measured from these specs")
            self.assertEqual(1, specs.call_count, "a second call measured the specs again")
            self.assertIs(first, second)
            generator.character_rates.cache_clear()
            generator.character_rates()
            self.assertEqual(2, specs.call_count,
                             "after cache_clear() the next call did not measure the specs")

    def test_the_ssl_context_is_built_once(self):
        from amaze.core import matx_sources
        self._fresh(matx_sources._ssl_context)
        with mock.patch.object(matx_sources, "ssl", wraps=ssl) as tls:
            first, second = matx_sources._ssl_context(), matx_sources._ssl_context()
            self.assertEqual(1, tls.create_default_context.call_count,
                             "a second call parsed the CA bundle again")
            self.assertIs(first, second)
            matx_sources._ssl_context.cache_clear()
            matx_sources._ssl_context()
            self.assertEqual(2, tls.create_default_context.call_count,
                             "after cache_clear() the next call did not build a context")

    def test_an_empty_theme_preference_is_read_once(self):
        from amaze.helpers import theme
        self._fresh(theme._read)
        with mock.patch.object(hou, "getPreference", return_value="") as asked:
            first = theme._read()
            once = asked.call_count
            second = theme._read()
            self.assertEqual([None, None], [first, second], "an empty preference read as a theme")
            self.assertEqual(once, asked.call_count,
                             "the None result was not cached, so the preference was read again")
            theme._read.cache_clear()
            theme._read()
            self.assertEqual(2 * once, asked.call_count,
                             "after cache_clear() the next call did not read the preference")

    def test_pillow_is_imported_once(self):
        from amaze.core import conversion
        self._fresh(conversion._have_pillow)
        with mock.patch.object(builtins, "__import__", side_effect=builtins.__import__) as imports:
            first, second = conversion._have_pillow(), conversion._have_pillow()
            pillow = [c for c in imports.call_args_list if c.args[:1] == ("PIL.Image",)]
            self.assertEqual(1, len(pillow), "a second call imported Pillow again")
            self.assertEqual(first, second)
            conversion._have_pillow.cache_clear()
            conversion._have_pillow()
            pillow = [c for c in imports.call_args_list if c.args[:1] == ("PIL.Image",)]
            self.assertEqual(2, len(pillow),
                             "after cache_clear() the next call did not import Pillow")

    def test_the_stock_lop_module_loads_once(self):
        from amaze.core import dragengine
        self._fresh(dragengine._load_stock_lop)
        with self._hh({"HH": self._stub_hh()}), self._specs() as specs:
            first, second = dragengine.stock_lop(), dragengine.stock_lop()
            self.assertEqual("stub", getattr(first, "LOADED", None), "the stub $HH was not loaded")
            self.assertEqual(1, specs.call_count, "a second call loaded the module again")
            self.assertIs(first, second)
            dragengine._load_stock_lop.cache_clear()
            dragengine.stock_lop()
            self.assertEqual(2, specs.call_count,
                             "after cache_clear() the next call did not load the module")

    def test_without_hh_each_call_logs_and_nothing_is_kept(self):
        """Without $HH nothing is cached: each call logs; once $HH is set, the next call loads."""
        from amaze.core import debug, dragengine
        self._fresh(dragengine._load_stock_lop)
        env, stub = {"HH": ""}, self._stub_hh()
        with self._hh(env), self._specs() as specs, \
                mock.patch.object(debug, "event") as logged:
            self.assertEqual([None, None], [dragengine.stock_lop(), dragengine.stock_lop()])
            self.assertEqual(["drag", "drag"], [c.args[0] for c in logged.call_args_list],
                             "a call without $HH was not logged, so its None was cached")
            self.assertEqual(0, specs.call_count, "a load was tried without $HH")
            env["HH"] = stub
            first, second = dragengine.stock_lop(), dragengine.stock_lop()
            self.assertEqual("stub", getattr(first, "LOADED", None),
                             "the result from before $HH was set was cached")
            self.assertEqual(1, specs.call_count, "the module did not load exactly once")
            self.assertIs(first, second)

    def test_a_failed_stock_lop_load_is_kept(self):
        from amaze.core import dragengine
        self._fresh(dragengine._load_stock_lop)
        with self._hh({"HH": self._scratch()}), self._specs() as specs:
            self.assertEqual([None, None], [dragengine.stock_lop(), dragengine.stock_lop()],
                             "a $HH without the module loaded something")
            self.assertEqual(1, specs.call_count, "a failed load was tried again")


if __name__ == "__main__":
    unittest.main()
