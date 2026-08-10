"""The save/load round-trip: the one path that touches irreplaceable
user data, tested against REAL files for the first time.

Everything else in the suite mocks this path (test_library asserts the
import function was *called*). Here a real Karma material is built with
distinctive parameter values, saved through the real funnel
(MaterialLibrary.add_asset -> NodeHandler.save_node -> .mat +
.interface on disk), the library is re-read from disk by a FRESH model
(persistence, not memory), re-imported into /mat through the real
importer, and the values are read back off the shader.

The failure half matters as much: a save that half-fails must never
leave a phantom row in the index - an entry that looks fine in the
grid until the day the files it points at are needed.

Uses the committed fixture library via test_support.fixture_prefs -
never the live one (preferences are keyword-injected; a positional
Prefs raises by design).
"""

import os
import stat
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

# THREE dirnames: tests/ -> amaze/ -> python/, the directory that
# holds the `amaze` package. The original had four, which lands on
# scripts/ - where amaze is NOT importable - so every one of these
# files silently imported amaze through Houdini's own package path,
# i.e. the INSTALL. The sync-before-test discipline masked it for the
# suite's whole life; it surfaced when a deliberately-unsynced
# sabotage edit failed to change a test's behaviour.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

from amaze.core import library as library_mod  # noqa: E402
from amaze.core import material  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402

#: Distinctive, non-default values - the point is proving THESE numbers
#: survive disk, not that a node with defaults reappears.
SPEC = {
    "base_color": (0.123, 0.456, 0.789),
    "specular_roughness": 0.321,
    "metalness": 1.0,
    "specular_IOR": 1.77,
}


def _build_material(parent: hou.Node, name: str) -> hou.Node:
    """A real Karma material through the real engine funnel."""

    def produce(builder):
        shader = builder.createNode("mtlxstandard_surface")
        for parm, value in SPEC.items():
            if isinstance(value, tuple):
                shader.parmTuple(parm).set(value)
            else:
                shader.parm(parm).set(value)
        return shader

    # By NAME: the engine hands back its wired verdict as a third field
    # (nodes.KarmaMaterial), and every helper that unpacked a bare pair
    # had to be visited when it stopped being one.
    return nodes.build_karma_material(parent, name, produce).builder


def _shader_of(builder: hou.Node):
    return next(n for n in builder.children()
                if n.type().name() == "mtlxstandard_surface")


class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # save_node() gates on $OCIO before anything else, and reports
        # its absence through hou.ui - which does not exist headless.
        # No render happens in these tests (render_on_import=0), so the
        # gate only needs the variable to be set.
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)
        mat = hou.node("/mat")
        self._mat_before = set(mat.children()) if mat else set()

    def tearDown(self):
        mat = hou.node("/mat")
        if mat:
            for child in set(mat.children()) - self._mat_before:
                try:
                    child.destroy()
                except hou.Error:
                    pass

    # -- the pair is one unit -------------------------------------------

    def test_a_failed_mat_write_does_not_destroy_the_interface(self):
        """The .interface and the .mat ARE one asset, and every save
        wrote the .interface FIRST with a truncating open, then
        attempted the .mat. A .mat write that failed - disk full,
        permissions, a cloud-sync hiccup, and this library lives in a
        synced folder - left the new .interface beside a stale or
        missing .mat, with the library row still pointing at the pair.

        Verified before the fix by forcing saveItemsToFile to fail on an
        Overwrite: the .interface had already been rewritten (57177
        bytes against the old 57023) and the previous good asset was
        unrecoverable."""
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        os.makedirs(base, exist_ok=True)
        interface = os.path.join(base, "pairtest.interface")
        mat = os.path.join(base, "pairtest" + self.prefs.ext)
        with open(interface, "w", encoding="utf-8") as handle:
            handle.write("OLD INTERFACE")
        with open(mat, "w", encoding="utf-8") as handle:
            handle.write("OLD MAT")

        handler = nodes.NodeHandler(self.prefs)

        def refuse(path):
            raise hou.OperationFailed("disk full")

        with self.assertRaises(hou.Error):
            handler.save_asset_pair(interface, mat, "NEW INTERFACE", refuse)

        with open(interface, encoding="utf-8") as handle:
            self.assertEqual(
                "OLD INTERFACE", handle.read(),
                "a failed .mat write destroyed the previous .interface")
        with open(mat, encoding="utf-8") as handle:
            self.assertEqual("OLD MAT", handle.read())

    def test_a_failed_save_leaves_no_temp_files(self):
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        os.makedirs(base, exist_ok=True)
        interface = os.path.join(base, "temptest.interface")
        mat = os.path.join(base, "temptest" + self.prefs.ext)
        handler = nodes.NodeHandler(self.prefs)

        with self.assertRaises(hou.Error):
            handler.save_asset_pair(
                interface, mat, "x",
                lambda path: (_ for _ in ()).throw(
                    hou.OperationFailed("nope")))

        leftovers = [n for n in os.listdir(base) if n.endswith(".writing")]
        self.assertEqual([], leftovers, "temp files survived a failed save")

    def test_a_mat_writer_that_writes_nothing_is_refused(self):
        """saveItemsToFile can return without raising and without
        producing a file; promoting a missing .mat would be the same
        loss by a quieter route."""
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        os.makedirs(base, exist_ok=True)
        interface = os.path.join(base, "silent.interface")
        mat = os.path.join(base, "silent" + self.prefs.ext)
        with open(interface, "w", encoding="utf-8") as handle:
            handle.write("OLD")
        handler = nodes.NodeHandler(self.prefs)

        with self.assertRaises(hou.Error):
            handler.save_asset_pair(interface, mat, "NEW", lambda path: None)
        with open(interface, encoding="utf-8") as handle:
            self.assertEqual("OLD", handle.read())

    def test_a_good_save_updates_both(self):
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        os.makedirs(base, exist_ok=True)
        interface = os.path.join(base, "good.interface")
        mat = os.path.join(base, "good" + self.prefs.ext)
        handler = nodes.NodeHandler(self.prefs)
        handler.save_asset_pair(
            interface, mat, "NEW INTERFACE",
            lambda path: open(path, "w", encoding="utf-8").write("NEW MAT"))
        with open(interface, encoding="utf-8") as handle:
            self.assertEqual("NEW INTERFACE", handle.read())
        with open(mat, encoding="utf-8") as handle:
            self.assertEqual("NEW MAT", handle.read())

    # -- what a save must NOT archive -----------------------------------

    def test_saving_a_bare_shader_does_not_archive_the_connector(self):
        """helpers.get_connected_nodes walks OUTPUTS as well as inputs,
        so from a bare shader inside a Karma builder it also collects
        the builder's own subnetconnector - measured:
        ['mtlxstandard_surface', 'mtlximage', 'subnetconnector'].

        Archiving that connector meant the import found TWO nodes
        answering "surface" and wired the loaded connector into itself,
        leaving the real one unwired: the material rendered pitch black
        while the import reported success."""
        builder = _build_material(self.staging, "bare_probe")
        shader = _shader_of(builder)
        texture = builder.createNode("mtlximage")
        shader.setInput(1, texture)

        self.model.add_asset(shader, "Bare", "", False)
        asset = self.model.assets[-1]

        handler = nodes.NodeHandler(self.prefs)
        ok, reason, _created = handler.import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)

        imported = handler.builder_node
        connectors = [c for c in imported.children()
                      if c.type().name() == "subnetconnector"
                      and "surface" in c.name()]
        self.assertEqual(
            1, len(connectors),
            "the saved material carried a duplicate surface connector: %s"
            % [c.name() for c in connectors])
        self.assertTrue(
            nodes.surface_terminal_wired(imported),
            "the imported material has nothing wired to its surface "
            "terminal - it renders black")

    def test_a_mantra_import_keeps_its_builder(self):
        """load_items_file(move_builder=False) moved the loaded children
        OUT of the rebuilt materialbuilder and destroyed it. Measured:
        five loose VOPs (surface_globals, displacement_globals, two
        outputs, output_collect) dumped straight into /mat, no material
        builder, material flag unset - and a later Rerender Thumbnail
        called cleanup(), which destroyed one and left the other four in
        the user's /mat permanently."""
        mat_ctx = hou.node("/mat")
        source = mat_ctx.createNode("materialbuilder", "mantra_src")
        source.setGenericFlag(hou.nodeFlag.Material, True)

        before = {n.path() for n in mat_ctx.children()}
        self.model.add_asset(source, "MantraProbe", "", False)
        asset = self.model.assets[-1]
        self.assertEqual(
            "Mantra", asset.renderer,
            "this test needs a Mantra asset to mean anything")
        self.assertTrue(
            asset.builder,
            "the saved asset did not record that it WAS a builder, so "
            "load_interface_mantra will skip the saved .interface")

        ok, reason, _created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            asset, target="mat")
        self.assertTrue(ok, reason)

        # By PATH: hou.Node wrappers are not identity-stable.
        created = [c for c in mat_ctx.children() if c.path() not in before]
        loose = [c for c in created if c.type().name() != "materialbuilder"]
        self.assertEqual(
            [], [c.name() for c in loose],
            "the Mantra import dumped loose VOPs into /mat instead of "
            "rebuilding a material")
        builders = [c for c in created
                    if c.type().name() == "materialbuilder"]
        self.assertEqual(1, len(builders), "expected exactly one builder")
        self.assertTrue(
            builders[0].children(),
            "the rebuilt builder is empty - its contents went elsewhere")
        for node in created:
            try:
                node.destroy()
            except Exception:            # noqa: BLE001 - already gone
                pass

    # -- clutter and containment ----------------------------------------

    def test_sop_imports_reuse_one_matnet(self):
        """_set_lop_import_path reuses a materiallibrary per the
        drop-placement law; the SOP twin created a fresh matnet every
        time. Measured: three imports into the same geo produced
        matnet1, matnet2, matnet3 with one material each."""
        geo = hou.node("/obj").createNode("geo", "sop_reuse_probe")
        self.addCleanup(geo.destroy)
        for _ in range(3):
            handler = nodes.NodeHandler(self.prefs)
            handler.get_current_network_node = lambda g=geo: g
            handler._set_sop_import_path()
        matnets = [c for c in geo.children()
                   if c.type().name() == "matnet"]
        self.assertEqual(
            1, len(matnets),
            "three imports left %d matnets in one geo" % len(matnets))

    def test_a_corrupt_interface_raises_a_hou_error_not_indexerror(self):
        """IndexError is not a hou.Error, so it bypassed
        import_asset_to_scene's handler entirely - and in the thumbnail
        path it fires BETWEEN layoutAboutToBeChanged and layoutChanged,
        leaving the Qt model with an unbalanced layout signal."""
        empty = hou.node("/obj").createNode("matnet", "empty_probe")
        self.addCleanup(empty.destroy)

        class _Mat:
            name = "probe"

        with self.assertRaises(hou.Error):
            nodes._first_child(empty, _Mat())

    def test_the_import_is_one_undo_entry(self):
        """Derived from the source: driving this needs a live panel, but
        the regression is structural - the loop must sit inside a
        hou.undos.group, like every other import entry point."""
        import re

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        match = re.search(
            r"def import_asset\(self.*?\n    def ", source, re.S)
        self.assertIsNotNone(match, "import_asset not found")
        self.assertIn(
            "hou.undos.group", match.group(0),
            "import_asset is not grouped - one Ctrl+Z leaves a stray "
            "matnet and a half-imported builder behind")

    def test_a_grid_verb_forces_no_layout_change_at_all(self):
        """This used to pin a `finally` around the re-render's
        `layoutAboutToBeChanged`/`layoutChanged` pair, because a
        corrupt asset raising between the two left every attached view
        believing a layout change was still running.

        The pair itself is gone (2026-08-03): it existed to force the
        proxy to re-map, and the proxy re-tests a changed row on its
        own now (core/grid_proxy.py). A verb that emits no layout
        change cannot leave one open - so what is pinned is the
        absence, for the verbs the Grid area owns.

        The wider rule still has teeth elsewhere: nine other panel
        methods open a layout change with no finally. They are recorded
        for batch 10, where a `relayout()` context manager collapses
        all of them; this test deliberately does not claim them."""
        import ast

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        verbs = {"grid_update_preview", "grid_toggle_favourite"}
        offenders = []
        for func in ast.walk(tree):
            if not (isinstance(func, ast.FunctionDef) and func.name in verbs):
                continue
            for node in ast.walk(func):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "emit"
                        and getattr(node.func.value, "attr", "").startswith(
                            "layout")):
                    offenders.append("%s:%d" % (func.name, node.lineno))
        self.assertEqual(
            [], offenders,
            "a grid verb is forcing a re-map by hand again, at %s - "
            "which is the thing that had to sit in a finally" % offenders)
        self.assertTrue(
            verbs <= {f.name for f in ast.walk(tree)
                      if isinstance(f, ast.FunctionDef)},
            "the grid verbs this checks no longer exist, so it is "
            "checking nothing")

    # -- the round-trip ------------------------------------------------

    def test_saved_material_survives_disk_and_reimports(self):
        rows_before = self.model.rowCount()
        builder = _build_material(self.staging, "roundtrip_mat")
        self.model.add_asset(builder, "RoundTrip", "roundtrip,test", False)

        # Registered exactly once, and stamped for later re-saves.
        self.assertEqual(self.model.rowCount(), rows_before + 1)
        mat_id = str(self.model.assets[-1].mat_id)
        self.assertEqual(builder.userData("assetlib_id"), mat_id)

        # Both halves of the archive exist and are non-empty.
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir, mat_id)
        for path in (base + self.prefs.ext, base + ".interface"):
            self.assertTrue(os.path.exists(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)

        # PERSISTENCE: a fresh model over the same directory - the row
        # must come back from library.json, not from memory.
        test_support.reset_database_singletons()
        reloaded = library_mod.MaterialLibrary(preferences=self.prefs)
        row = reloaded.find_asset_row_by_id(mat_id)
        self.assertNotEqual(row, -1, "saved row missing after reload")
        asset = reloaded.assets[row]
        self.assertEqual(asset.name, "roundtrip_mat")
        self.assertIn("RoundTrip", asset.categories)

        # RE-IMPORT through the real importer, into /mat.
        ok, reason, _created = reloaded.import_asset_to_scene(
            reloaded.index(row, 0), target="mat"
        )
        self.assertTrue(ok, reason)
        imported = [n for n in hou.node("/mat").children()
                    if n not in self._mat_before
                    and n.userData("assetlib_id") == mat_id]
        self.assertEqual(len(imported), 1,
                         "expected exactly one imported node")
        node = imported[0]

        # The material is USABLE, not merely present.
        self.assertTrue(node.isMaterialFlagSet())
        self.assertTrue(nodes.surface_terminal_wired(node),
                        "imported material would render black")

        # And the VALUES survived the round-trip.
        shader = _shader_of(node)
        for parm, want in SPEC.items():
            got = shader.parmTuple(parm).eval()
            expect = want if isinstance(want, tuple) else (want,)
            for g, w in zip(got, expect):
                self.assertAlmostEqual(g, w, places=5,
                                       msg="%s did not survive" % parm)

    def test_reimport_is_repeatable(self):
        """Importing the same asset twice must yield two independent,
        working nodes - not a collision or a half-wired copy."""
        builder = _build_material(self.staging, "twice_mat")
        self.model.add_asset(builder, "RoundTrip", "", False)
        row = self.model.rowCount() - 1
        for _ in range(2):
            ok, reason, _created = self.model.import_asset_to_scene(
                self.model.index(row, 0), target="mat"
            )
            self.assertTrue(ok, reason)
        fresh = [n for n in hou.node("/mat").children()
                 if n not in self._mat_before]
        self.assertEqual(len(fresh), 2)
        for node in fresh:
            self.assertTrue(nodes.surface_terminal_wired(node))

    # -- the failure half ----------------------------------------------

    @unittest.skipUnless(sys.platform != "win32",
                         "chmod cannot make a directory unwritable on "
                         "Windows - the failure this test injects does "
                         "not happen there")
    def test_failed_save_leaves_no_phantom_row(self):
        """A save whose file write fails must not register the asset:
        a row without files is the phantom that looks fine in the grid
        until the day it is needed. (Files without a row are the safe
        direction - Clean Up Library collects those.)

        WINDOWS: skipped, and the skip is the honest answer rather than
        a weaker assertion. MEASURED 2026-08-06: `os.chmod(d, 0o555)`
        on a directory reports mode 0o555 back and a write INTO it
        still succeeds, so the save never fails, the row is registered,
        and the test reports a phantom row for behaviour that is
        correct. Restoring the coverage needs a different injection -
        the write has to be made to fail some other way - not a
        different assertion.
        """
        rows_before = self.model.rowCount()
        index_path = os.path.join(self.prefs.dir, "library.json")
        index_before = open(index_path, "rb").read()

        mats_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        builder = _build_material(self.staging, "doomed_mat")
        os.chmod(mats_dir, stat.S_IRUSR | stat.S_IXUSR)   # no write
        self.addCleanup(os.chmod, mats_dir,
                        stat.S_IRWXU)                     # restore
        try:
            try:
                self.model.add_asset(builder, "RoundTrip", "", False)
            except (OSError, hou.Error):
                pass          # raising is acceptable; registering is not
        finally:
            os.chmod(mats_dir, stat.S_IRWXU)

        self.assertEqual(self.model.rowCount(), rows_before,
                         "failed save registered a phantom row")
        self.assertEqual(open(index_path, "rb").read(), index_before,
                         "failed save rewrote library.json")
        self.assertIsNone(builder.userData("assetlib_id"),
                          "failed save stamped the node as saved")

    def test_missing_mat_file_import_fails_cleanly(self):
        """An index row whose .mat file is gone (the phantom this suite
        exists to prevent) must refuse to import - with a reason, not a
        traceback, and without leaving debris in /mat."""
        builder = _build_material(self.staging, "vanishing_mat")
        self.model.add_asset(builder, "RoundTrip", "", False)
        row = self.model.rowCount() - 1
        mat_id = str(self.model.assets[row].mat_id)
        os.remove(os.path.join(self.prefs.dir, self.prefs.asset_dir,
                               mat_id + self.prefs.ext))
        try:
            ok, reason, _created = self.model.import_asset_to_scene(
                self.model.index(row, 0), target="mat"
            )
        except hou.Error:
            ok, reason = False, "raised hou.Error"
        self.assertFalse(ok)
        fresh = [n for n in hou.node("/mat").children()
                 if n not in self._mat_before
                 and n.userData("assetlib_id") == mat_id]
        self.assertEqual(fresh, [], "failed import left debris in /mat")


class TheRedshiftAndOctaneSaveIsOneSave(unittest.TestCase):
    """`save_node_redshift` and `save_node_octane` were eighty lines
    each, identical but for two log strings and the thumbnail call.
    They are one function now, told which thumbnail to run BY NAME.

    NO TEST IN THE SUITE BUILDS A REDSHIFT OR OCTANE MATERIAL, so
    neither path runs here - on either Houdini version, and whatever is
    installed. A mistyped thumbnail name would therefore surface for
    the first time on a real save, after the files had already been
    written. That is what these two tests exist to prevent.

    Not "the renderers are absent" - they are not. Redshift is
    installed on **H21** (Maxon has an open bug on H22, so it is
    missing there, which is what the debug log's `has_redshift: false`
    means on a 22.x session and nothing more); Octane is arriving. The
    gap is the FIXTURES, not the machine.
    """

    def _shared_calls(self):
        import ast
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "render", "nodes.py")
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        found = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "")
                    == "_save_staged_with_cop_companion"):
                found.append([a.value for a in node.args
                              if isinstance(a, ast.Constant)])
        return found

    def test_both_renderers_reach_the_shared_save(self):
        calls = self._shared_calls()
        self.assertEqual(
            2, len(calls),
            "the Redshift and Octane entry points no longer both route "
            "through one save - found %d call sites" % len(calls))

    def test_every_thumbnail_named_there_actually_exists(self):
        """WHAT WOULD BREAK THIS: renaming a `create_thumb_*` method,
        or a typo in the name passed to the shared save. Neither raises
        until a real Redshift or Octane material is saved."""
        from amaze.render import thumbs as thumbs_mod
        named = [args[-1] for args in self._shared_calls() if args]
        self.assertTrue(named, "no thumbnail method names found to check")
        for name in named:
            self.assertTrue(
                hasattr(thumbs_mod.ThumbNailRenderer, name),
                "the shared save dispatches to ThumbNailRenderer.%s, "
                "which does not exist - a save on a machine with that "
                "renderer would raise after writing the files" % name)


class TestUnsafeAssetIds(unittest.TestCase):
    """An id out of library.json becomes a FILENAME, so it decides which
    file the loader opens. The app authors ids as uuid4 hex, but it does
    not author the index alone - a library can arrive edited, synced or
    damaged - so the id is checked before it is composed into a path.

    Both halves are tested: the boundary check that rejects the shape,
    and the containment that catches an escape the shape check missed.
    """

    def test_the_shapes_real_libraries_actually_hold_are_accepted(self):
        """Guards the guard. The first spec for this was "32 hex only",
        which would refuse the committed fixture (six 18-digit legacy
        timestamp ids and a "-1" row) and every pre-uuid library."""
        for good in ("00755b7004824333af08d921462fa3ae",
                     "139888336268658010", "-1", "a", "A_b-c.d"):
            self.assertTrue(material.is_safe_asset_id(good), good)

    def test_traversal_and_separators_are_refused(self):
        for bad in ("../../.ssh/authorized_keys", "..", ".",
                    "a/b", "a\\b", "", "x" * 65, "a b", "a\x00b"):
            self.assertFalse(material.is_safe_asset_id(bad), repr(bad))

    def test_contained_join_refuses_an_escape(self):
        base = tempfile.mkdtemp(prefix="amaze_contain_")
        self.addCleanup(shutil.rmtree, base, True)
        inside = hostos.contained_join(base, "mat/", "asset.mat")
        self.assertTrue(inside.startswith(base))
        with self.assertRaises(hostos.PathEscape):
            hostos.contained_join(base, "mat/", "../../escaped.mat")

    def test_payload_path_composes_what_the_concatenations_did(self):
        """The twenty render sites that used to write

            preferences.dir + preferences.asset_dir + id + suffix

        must get the SAME string from payload_path, or this was not a
        consolidation. Break payload_path's composition and this fails
        on the strings, not on a downstream symptom.
        """
        base = tempfile.mkdtemp(prefix="amaze_payload_")
        self.addCleanup(shutil.rmtree, base, True)

        class _P:
            asset_dir = "mat/"
            ext = ".mat"
            dir = base + os.sep

        for suffix in (_P.ext, ".interface", ".builder.json",
                       "_cop" + _P.ext):
            self.assertEqual(
                _P.dir + _P.asset_dir + "abc" + suffix,
                material.payload_path(_P, "abc", suffix),
                "payload_path no longer composes what the twenty "
                "hand-written concatenations did, for %r" % suffix)

    def test_payload_path_does_not_need_dirs_trailing_separator(self):
        """WHAT WOULD BREAK THIS: going back to `+`.

        `Prefs.save()` is the only thing that puts the separator on
        `dir`, and it runs nowhere near the twenty readers that used to
        assume it. Concatenation gives `<lib>mat/abc.mat` without it;
        composition does not care.
        """
        base = tempfile.mkdtemp(prefix="amaze_payload_")
        self.addCleanup(shutil.rmtree, base, True)

        class _Unslashed:
            asset_dir = "mat/"
            ext = ".mat"
            dir = base                      # no trailing separator

        # normpath BOTH sides: `asset_dir` carries a literal "mat/", so
        # on Windows the composed path is `<base>\mat/abc.mat` - correct
        # and openable, but not string-equal to os.path.join's
        # `<base>\mat\abc.mat`. This test is about COMPOSITION versus
        # concatenation, not about which separator the OS prefers, and
        # comparing the raw strings failed it on Windows for the one
        # reason it does not care about.
        self.assertEqual(
            os.path.normpath(os.path.join(base, "mat", "abc.mat")),
            os.path.normpath(material.payload_path(_Unslashed, "abc",
                                                   ".mat")),
            "a library path without its trailing separator composed "
            "wrong - which is what concatenation did here")

    def test_payload_path_refuses_an_escaping_id(self):
        """The door the renderers did not have. `is_safe_asset_id`
        guards the RECORD; this guards the PATH, and the save/thumbnail
        route only ever had the first one."""
        base = tempfile.mkdtemp(prefix="amaze_payload_")
        self.addCleanup(shutil.rmtree, base, True)

        class _P:
            asset_dir = "mat/"
            ext = ".mat"
            dir = base + os.sep

        with self.assertRaises(hostos.PathEscape):
            material.payload_path(_P, "../../.ssh/authorized_keys", ".mat")

    def test_contained_join_refuses_a_symlink_out(self):
        """The shape check cannot see this one: the id is clean and the
        hop out is a link someone planted in the asset directory."""
        base = tempfile.mkdtemp(prefix="amaze_contain_")
        self.addCleanup(shutil.rmtree, base, True)
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        os.makedirs(os.path.join(base, "mat"))
        os.symlink(outside, os.path.join(base, "mat", "away"))
        with self.assertRaises(hostos.PathEscape):
            hostos.contained_join(base, "mat", "away", "asset.mat")

    def test_an_import_with_a_traversal_id_is_refused(self):
        """End to end, through the real importer: the refusal names the
        material, nothing is created, and the file it would have read is
        never opened."""
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

        index_path = os.path.join(prefs_obj.dir, "library.json")
        with open(index_path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["assets"][0]["id"] = "../../.ssh/authorized_keys"
        data["assets"][0]["name"] = "tampered"
        with open(index_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        row = model.find_asset_row_by_id("../../.ssh/authorized_keys")
        self.assertNotEqual(row, -1, "premise: the tampered row loaded")

        before = set(hou.node("/mat").children())
        ok, reason, _created = model.import_asset_to_scene(model.index(row, 0),
                                                 target="mat")
        self.assertFalse(ok, "a traversal id was imported")
        self.assertIn("tampered", reason)
        self.assertEqual(before, set(hou.node("/mat").children()),
                         "a refused import still created a node")


class TestInterfaceIsNeverExecuted(unittest.TestCase):
    """`.interface` is asCode() output - Python whose only documented
    contract is that it RUNS - and the loader used to run it, choosing
    the file with an id read verbatim out of library.json.

    It is now read for its builder type by regex and nothing more. The
    container's own parameter interface comes from a sidecar that is
    parsed. These prove the execution is gone, not merely guarded.
    """

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def test_payload_in_an_interface_file_does_not_run(self):
        marker = os.path.join(tempfile.mkdtemp(prefix="amaze_exec_"), "ran")
        self.addCleanup(shutil.rmtree, os.path.dirname(marker), True)

        row = next(r for r in range(self.model.rowCount())
                   if str(self.model.assets[r].renderer))
        asset = self.model.assets[row]
        target = os.path.join(self.prefs.dir, self.prefs.asset_dir,
                              asset.mat_id + ".interface")
        self.assertTrue(os.path.exists(target), "premise: the pair exists")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(
                "import pathlib\n"
                "pathlib.Path(%r).write_text('executed')\n"
                "hou_node = hou_parent.createNode('subnet')\n" % marker)

        # The import may succeed or refuse - what must NOT happen is the
        # payload running. Asserting only "it still imports" would pass
        # just as well with exec() restored.
        self.model.import_asset_to_scene(self.model.index(row, 0), target="mat")
        self.assertFalse(
            os.path.exists(marker),
            "the .interface file was EXECUTED - the import path is running "
            "code out of a file the library index chose")

    def test_a_sidecar_round_trips_interface_and_values(self):
        """What the sidecar has to preserve, proven both ways."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")

        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_probe", "Probe", 1,
                                           default_value=(0.25,)))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_probe").set(0.75)

        captured = nodes.capture_builder(builder)
        self.assertIn("amaze_probe", captured)

        fresh = staging.createNode("subnet")
        self.assertIsNone(fresh.parm("amaze_probe"),
                          "premise: the spare parm is not there by default")
        nodes.apply_builder(fresh, json.loads(captured))
        self.assertIsNotNone(fresh.parm("amaze_probe"),
                             "the sidecar did not restore the interface")
        self.assertAlmostEqual(0.75, fresh.parm("amaze_probe").eval(), 5,
                               "the sidecar restored the parm but not its "
                               "value")

    def test_a_promoted_RAMP_round_trips_through_its_components(self):
        """A ramp promoted to the builder's interface is the ordinary
        one-dial-for-the-material move, and it survives - by a route
        worth pinning, because reading the code suggests otherwise.

        `json.dumps` sits OUTSIDE the per-parm guard, and `hou.Ramp` is
        not serialisable, so capture LOOKS one dialled ramp away from
        raising `TypeError` past `save_asset_pair`. Measured 2026-08-10:
        it is not. A ramp's container parm reports `isAtDefault()` True
        even once dialled, so `capture_builder` never evaluates it; what
        it walks are the backing components - `<name>1value`,
        `<name>2pos`, `<name>2value` - which are Floats.

        So this pins the round trip, not a refusal: the shape comes back
        from the dialog script and the values from the components."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")

        group = builder.parmTemplateGroup()
        group.append(hou.RampParmTemplate("amaze_ramp", "Ramp",
                                          hou.rampParmType.Float))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_ramp").set(
            hou.Ramp((hou.rampBasis.Linear, hou.rampBasis.Linear),
                     (0.0, 1.0), (0.2, 0.9)))

        captured = nodes.capture_builder(builder)          # must not raise
        document = json.loads(captured)
        self.assertIn(
            "amaze_ramp", document["dialog_script"],
            "the ramp's shape is not in the captured interface")
        self.assertTrue(
            [k for k in document["values"] if k.startswith("amaze_ramp")],
            "no ramp component value was captured, so a dialled ramp "
            "comes back at its default: %s" % sorted(document["values"]))

        fresh = staging.createNode("subnet")
        nodes.apply_builder(fresh, document)
        restored = fresh.parm("amaze_ramp")
        self.assertIsNotNone(restored,
                             "the sidecar did not restore the ramp")
        self.assertAlmostEqual(
            0.9, restored.evalAsRamp().lookup(1.0), 5,
            "the ramp came back at its default value")

    def test_a_value_the_sidecar_cannot_serialise_costs_only_that_parm(self):
        """The guard the measurement above says nothing reaches today.

        `json.dumps` runs over the whole document AFTER the loop, so a
        value it refuses would raise `TypeError` - which
        `save_asset_pair` does not catch, three lines below a comment
        saying a sidecar that cannot be built must not cost the asset.
        No shipped parm type gets there; this pins the behaviour for
        the one that eventually does."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")
        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_keeps", "Keeps", 1,
                                           default_value=(0.25,)))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_keeps").set(0.75)

        from unittest.mock import patch

        real_eval = hou.Parm.eval

        def poisoned(self):
            if self.name() == "amaze_keeps":
                return object()          # nothing json can take
            return real_eval(self)

        with patch.object(hou.Parm, "eval", poisoned):
            captured = nodes.capture_builder(builder)      # must not raise
        self.assertNotIn(
            "amaze_keeps", json.loads(captured)["values"],
            "the unserialisable parm was captured anyway")

    def test_an_absent_sidecar_is_not_an_error(self):
        """Every asset saved before the format existed has none, and the
        loader degrades rather than refusing."""
        self.assertEqual({}, nodes.read_builder_sidecar(
            os.path.join(self.prefs.dir, "does-not-exist.builder.json")))

    def test_a_damaged_sidecar_is_reported_not_raised(self):
        broken = os.path.join(self.prefs.dir, "broken.builder.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        with test_support.captured_log() as log:
            self.assertEqual({}, nodes.read_builder_sidecar(broken))
        self.assertTrue(log.matching("builder sidecar unreadable", "import"),
                        "a damaged sidecar was swallowed silently")


class UpdateExistingIsGuardedAgainstTheOtherSessionTest(unittest.TestCase):
    """Two sessions both doing a structural Update Existing to the same
    id silently last-write-wins the .mat/.interface pair - the one
    write that stays exclusive even after Versions, because content is
    outside the index merge entirely."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def _their_write(self, mat_id):
        """Another session replaces the .mat underneath this one."""
        path = self.model.asset_files(mat_id)["mat"]
        with open(path, "ab") as fh:
            fh.write(b"\0their-bytes")
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns,
                           stat.st_mtime_ns + 5_000_000_000))

    def test_a_changed_mat_refuses_the_update(self):
        row = next(r for r in range(self.model.rowCount())
                   if str(self.model.assets[r].renderer))
        mat = self.model.assets[row]
        before = open(self.model.asset_files(mat.mat_id)["mat"],
                      "rb").read()
        self._their_write(mat.mat_id)
        theirs = open(self.model.asset_files(mat.mat_id)["mat"],
                      "rb").read()

        node = self.staging.createNode("subnet")
        result = self.model.update_asset_content(row, node)

        self.assertEqual("", result,
                         "the update overwrote content another session "
                         "wrote since this one read it")
        now = open(self.model.asset_files(mat.mat_id)["mat"],
                   "rb").read()
        self.assertEqual(theirs, now,
                         "the refusal still modified their file")
        self.assertNotEqual(before, now, "premise check")

    def test_our_own_update_rebaselines(self):
        """A session's own write must not trip its own guard - two
        updates in a row from one session are ordinary use."""
        # is_karma_renderer, not a literal match: the stored value is
        # "MaterialX" but the renderer property NORMALISES - matching
        # the raw string found nothing.
        row = next(r for r in range(self.model.rowCount())
                   if material.is_karma_renderer(
                       self.model.assets[r].renderer))
        node = _build_material(self.staging, "update_guard_probe")
        first = self.model.update_asset_content(row, node)
        self.assertTrue(first, "premise: the first update lands")
        second = self.model.update_asset_content(row, node)
        self.assertTrue(second,
                        "a session's own write tripped its own guard - "
                        "the baseline was not refreshed")


class StructureSignatureTest(unittest.TestCase):
    """The Versions decision rule: same nodes, same wiring, only values
    differ -> a new version; anything else -> the structural path. The
    signature is what answers it, so its two directions ARE the
    feature's correctness."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_a_parameter_edit_keeps_the_signature(self):
        builder = _build_material(self.staging, "sig_parm_probe")
        before = nodes.structure_signature(builder)
        shader = _shader_of(builder)
        # A guaranteed SCALAR parm: SPEC's first key can be a tuple
        # (colours), whose .parm() is None - .parmTuple territory.
        scalar = next(parm for parm in shader.parms()
                      if parm.parmTemplate().numComponents() == 1
                      and parm.parmTemplate().type()
                      == hou.parmTemplateType.Float)
        scalar.set(scalar.eval() + 0.111)
        self.assertEqual(before, nodes.structure_signature(builder),
                         "a value edit changed the structure signature - "
                         "every parameter tweak would take the structural "
                         "path and Versions would never fire")

    def test_layout_moves_keep_the_signature(self):
        builder = _build_material(self.staging, "sig_layout_probe")
        before = nodes.structure_signature(builder)
        for child in builder.children():
            child.move(hou.Vector2(3.0, -2.0))
        self.assertEqual(before, nodes.structure_signature(builder),
                         "canvas layout leaked into the signature")

    def test_an_added_node_changes_it(self):
        builder = _build_material(self.staging, "sig_add_probe")
        before = nodes.structure_signature(builder)
        builder.createNode("mtlximage", "sig_added")
        self.assertNotEqual(before, nodes.structure_signature(builder),
                            "an added node did not change the signature - "
                            "a structural edit would silently become a "
                            "version")

    def test_a_rewire_changes_it(self):
        builder = _build_material(self.staging, "sig_wire_probe")
        image = builder.createNode("mtlximage", "sig_wire_img")
        shader = _shader_of(builder)
        before = nodes.structure_signature(builder)
        shader.setInput(0, image)
        self.assertNotEqual(before, nodes.structure_signature(builder),
                            "a rewire did not change the signature")

    def test_staged_asset_loads_and_cleans_up(self):
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(r for r in range(model.rowCount())
                   if material.is_karma_renderer(model.assets[r].renderer))
        mat = model.assets[row]
        obj_before = set(hou.node("/obj").children())
        signature = nodes.staged_asset(self.prefs, mat,
                                       nodes.structure_signature)
        self.assertTrue(signature and len(signature) == 16)
        self.assertEqual(obj_before, set(hou.node("/obj").children()),
                         "staged_asset left its staging network in /obj")

    def test_staged_asset_cleans_up_even_when_the_loader_raises(self):
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(r for r in range(model.rowCount())
                   if material.is_karma_renderer(model.assets[r].renderer))
        obj_before = set(hou.node("/obj").children())

        def boom(_node):
            raise RuntimeError("loader failure")

        with self.assertRaises(RuntimeError):
            nodes.staged_asset(self.prefs, model.assets[row], boom)
        self.assertEqual(obj_before, set(hou.node("/obj").children()),
                         "a raising loader stranded the staging network")


if __name__ == "__main__":
    unittest.main()
