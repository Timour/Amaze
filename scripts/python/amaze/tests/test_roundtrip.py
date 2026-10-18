"""The save/load round-trip against REAL files - the one path that touches irreplaceable user data, where everything else in the suite mocks it. A real Karma material with distinctive values goes through the real funnel to disk, is re-read by a FRESH model, re-imported through the real importer, and read back off the shader. The failure half matters as much: a save that half-fails must never leave a phantom row. Runs on the committed fixture library via test_support.fixture_prefs, never the live one."""

import os
import stat
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(  # THREE dirnames: tests/ -> amaze/ -> python/, the directory holding the `amaze` package. FOUR lands on scripts/, where amaze is not importable, and the run silently tests the INSTALL instead ▸p/checkout-not-install
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


def _redshift_available():
    """Same probe test_redshift_terminal.py uses: ask for the TYPE. It skips only where Redshift genuinely is not installed - never on every host at once, which would make it dead cover. ▸r/renderer-plugins"""
    try:
        return hou.vopNodeTypeCategory().nodeType(
            "redshift_vopnet") is not None
    except Exception:                                        # noqa: BLE001
        return False

SPEC = {  # distinctive, non-default values: the point is proving THESE numbers survive disk, not that a node with defaults reappears
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

    return nodes.build_karma_material(parent, name, produce).builder  # by NAME: the engine hands back a nodes.KarmaMaterial, and every helper that unpacked a bare pair had to be visited when it stopped being one


def _shader_of(builder: hou.Node):
    return next(n for n in builder.children()
                if n.type().name() == "mtlxstandard_surface")


class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if hou.getenv("OCIO") is None:  # save_node() gates on $OCIO first and reports its absence through hou.ui, which does not exist headless; nothing renders here, so the gate only needs the variable set
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

    def test_a_mat_write_that_fails_or_writes_nothing_keeps_the_old_pair(self):
        """The .interface and the .mat ARE one asset: neither half may move alone. ▸p/asset-write-unit"""
        base = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        os.makedirs(base, exist_ok=True)
        interface = os.path.join(base, "pairtest.interface")
        mat = os.path.join(base, "pairtest" + self.prefs.ext)
        handler = nodes.NodeHandler(self.prefs)

        def refuse(path):
            raise hou.OperationFailed("disk full")

        for why, writer in (("the write raises", refuse),
                            ("the writer returns with no file", lambda path: None)):
            with self.subTest(why):
                with open(interface, "w", encoding="utf-8") as handle:
                    handle.write("OLD INTERFACE")
                with open(mat, "w", encoding="utf-8") as handle:
                    handle.write("OLD MAT")
                with self.assertRaises(hou.Error):
                    handler.save_asset_pair(interface, mat, "NEW INTERFACE", writer)
                with open(interface, encoding="utf-8") as handle:
                    self.assertEqual(
                        "OLD INTERFACE", handle.read(),
                        "a failed .mat write destroyed the previous .interface")
                with open(mat, encoding="utf-8") as handle:
                    self.assertEqual("OLD MAT", handle.read())
                self.assertEqual([], [n for n in os.listdir(base) if n.endswith(".writing")],
                                 "temp files survived a failed save")

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

    def test_saving_a_bare_shader_does_not_archive_the_connector(self):  # -- what a save must NOT archive --
        """helpers.get_connected_nodes walks OUTPUTS as well as inputs, so from a bare shader inside a Karma builder it also collects the builder's own subnetconnector - and archiving that leaves the import with TWO nodes answering "surface", the real one unwired and the material rendering pitch black while the import reports success."""
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

    def test_a_save_of_a_builders_contents_imports_with_one_set_of_terminals(self):
        """A save holding the builder's own connectors imports with them alone, wired. ▸r/save-shape"""
        asset = next(a for a in self.model.assets if a.name == "plastic")    # such a save
        handler = nodes.NodeHandler(self.prefs)
        ok, reason, _created = handler.import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)
        imported = handler.builder_node
        outputs = sorted((c.name(), c.parm("parmname").eval()) for c in imported.children()
                         if c.type().name() == "subnetconnector"
                         and c.parm("connectorkind").eval() == 1)
        self.assertEqual([("displacement_output", "displacement"),
                          ("surface_output", "surface")], outputs,
                         "the import holds a second set of output connectors")
        self.assertTrue(nodes.surface_terminal_wired(imported),
                        "the imported material renders the default grey")
        self.assertEqual(1, len([c for c in imported.children()
                                 if c.type().name() == "subinput"]))

    @unittest.skipUnless(_redshift_available(),
                         "the Redshift plugin is not loaded")
    def test_an_import_keeps_its_builder(self):
        """A rebuilt container is KEPT and moved, not gutted - moving the loaded children OUT and destroying it dumps loose VOPs into /mat with no material node, which a later Rerender Thumbnail then half-cleans and leaves permanently."""
        mat_ctx = hou.node("/mat") or hou.node("/").createNode("mat")
        source = mat_ctx.createNode("redshift_vopnet", "rs_src")
        source.setGenericFlag(hou.nodeFlag.Material, True)

        before = {n.path() for n in mat_ctx.children()}
        self.model.add_asset(source, "RedshiftProbe", "", False)
        asset = self.model.assets[-1]
        self.assertEqual(
            "Redshift", asset.renderer,
            "this test needs a Redshift asset to mean anything")

        ok, reason, _created = nodes.NodeHandler(
            self.prefs).import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)

        created = [c for c in mat_ctx.children() if c.path() not in before]  # by PATH: hou.Node wrappers are not identity-stable
        loose = [c for c in created
                 if c.type().name() != "redshift_vopnet"]
        self.assertEqual(
            [], [c.name() for c in loose],
            "the import dumped loose VOPs into /mat instead of "
            "rebuilding a material")
        builders = [c for c in created
                    if c.type().name() == "redshift_vopnet"]
        self.assertEqual(1, len(builders), "expected exactly one builder")
        self.assertTrue(
            builders[0].children(),
            "the rebuilt builder is empty - its contents went elsewhere")
        for node in created:
            try:
                node.destroy()
            except Exception:            # noqa: BLE001 - already gone
                pass

    def test_sop_imports_reuse_one_matnet(self):  # -- clutter and containment --
        """_set_lop_import_path reuses a materiallibrary per the drop-placement law, and the SOP twin must do the same - creating a fresh matnet per import leaves matnet1, matnet2, matnet3 with one material each."""
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

    def _failing_lop_import(self, stage):
        """Import a Karma asset whose `.mat` is damaged into `stage`; answers the import's ok."""
        asset = next(a for a in self.model.assets
                     if material.is_karma_renderer(a.renderer))
        payload = material.payload_path(self.prefs, asset.mat_id,
                                        self.prefs.ext)
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write("not an items file")
        ok, _reason, _created = nodes.NodeHandler(
            self.prefs).import_asset_to_scene(
                asset, target="lop", context_node=stage)
        return ok

    def _libraries(self, stage):
        return [c.name() for c in stage.children()
                if c.type().name() == "materiallibrary"]

    def test_a_failed_import_takes_back_only_the_library_it_made(self):
        for probe, theirs, left in (("failed_import_probe", None, []),
                                    ("kept_library_probe", "theirs", ["theirs"])):
            with self.subTest(existing=theirs):
                stage = hou.node("/obj").createNode("lopnet", probe)
                self.addCleanup(stage.destroy)
                if theirs:
                    stage.createNode("materiallibrary", theirs)
                self.assertFalse(self._failing_lop_import(stage),
                                 "premise: a damaged .mat must fail the import")
                self.assertEqual(
                    left, self._libraries(stage),
                    "a failed import left the library it made, or removed "
                    "one it only reused")

    def _karma_asset(self):
        return next(a for a in self.model.assets
                    if material.is_karma_renderer(a.renderer))

    def _assert_refused_plainly(self, handler, stage):
        """The staging failure answers the plain sentence naming the material, never a raise."""
        from amaze import messages
        asset = self._karma_asset()
        try:
            ok, reason, created = handler.import_asset_to_scene(
                asset, target="lop", context_node=stage)
        except hou.Error as exc:
            self.fail("the staging failure raised instead of answering: %s"
                      % exc)
        self.assertFalse(ok)
        self.assertEqual(
            messages.MATERIAL_FAILED_TO_IMPORT % asset.name, reason)
        self.assertEqual([], created)

    def test_a_companion_that_raises_takes_back_the_library_made(self):
        stage = hou.node("/obj").createNode("lopnet", "companion_raise_probe")
        self.addCleanup(stage.destroy)
        handler = nodes.NodeHandler(self.prefs)

        def refusing(mat):
            raise hou.OperationFailed("companion refused")

        handler.restore_cop_companion = refusing
        self._assert_refused_plainly(handler, stage)
        self.assertEqual([], self._libraries(stage),
                         "the import left the library it made when the COP "
                         "companion raised")
        self.assertIsNone(handler._context_override,
                          "the import kept the context it was handed")

    def test_a_staging_failure_takes_back_the_companion_restored(self):
        """The companion is restored before the staging network exists, and both are the import's."""
        stage = hou.node("/obj").createNode("lopnet", "staging_raise_probe")
        self.addCleanup(stage.destroy)
        real_node = hou.node
        self.addCleanup(lambda: [n.destroy() for n in
                                 [real_node("/obj/staging_probe_cops")]
                                 if n is not None])
        handler = nodes.NodeHandler(self.prefs)
        handler.restore_cop_companion = lambda mat: real_node(
            "/obj").createNode("copnet", "staging_probe_cops")

        class RefusesStaging:
            def __init__(self, node):
                self._node = node

            def createNode(self, type_name, *args, **kwargs):
                if type_name == "matnet":
                    raise hou.OperationFailed("staging refused")
                return self._node.createNode(type_name, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._node, name)

        def node(path):
            found = real_node(path)
            return RefusesStaging(found) if path == "/obj" else found

        with mock.patch.object(hou, "node", node):
            self._assert_refused_plainly(handler, stage)
        self.assertIsNone(real_node("/obj/staging_probe_cops"),
                          "the import left the COP companion it restored")
        self.assertEqual([], self._libraries(stage))

    def test_the_import_is_one_undo_entry(self):
        """Derived from the SOURCE, because driving it needs a live panel: the loop must sit inside a hou.undos.group, like every other import entry point. ▸p/source-derived-tests"""
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

    def test_saved_material_survives_disk_and_reimports(self):  # -- the round-trip --
        rows_before = self.model.rowCount()
        builder = _build_material(self.staging, "roundtrip_mat")
        self.model.add_asset(builder, "RoundTrip", "roundtrip,test", False)

        self.assertEqual(self.model.rowCount(), rows_before + 1)  # registered exactly once, and stamped for later re-saves
        mat_id = str(self.model.assets[-1].mat_id)
        self.assertEqual(builder.userData("assetlib_id"), mat_id)

        base = os.path.join(self.prefs.dir, self.prefs.asset_dir, mat_id)  # both halves of the archive exist and are non-empty
        for path in (base + self.prefs.ext, base + ".interface"):
            self.assertTrue(os.path.exists(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)

        test_support.reset_database_singletons()  # PERSISTENCE: a fresh model over the same directory, so the row comes back from library.json rather than from memory
        reloaded = library_mod.MaterialLibrary(preferences=self.prefs)
        row = reloaded.find_asset_row_by_id(mat_id)
        self.assertNotEqual(row, -1, "saved row missing after reload")
        asset = reloaded.assets[row]
        self.assertEqual(asset.name, "roundtrip_mat")
        self.assertIn("RoundTrip", asset.categories)

        ok, reason, _created = reloaded.import_asset_to_scene(  # RE-IMPORT through the real importer, into /mat
            reloaded.index(row, 0), target="mat"
        )
        self.assertTrue(ok, reason)
        imported = [n for n in hou.node("/mat").children()
                    if n not in self._mat_before
                    and n.userData("assetlib_id") == mat_id]
        self.assertEqual(len(imported), 1,
                         "expected exactly one imported node")
        node = imported[0]

        self.assertTrue(node.isMaterialFlagSet())  # USABLE, not merely present
        self.assertTrue(nodes.surface_terminal_wired(node),
                        "imported material would render black")

        shader = _shader_of(node)  # and the VALUES survived the round-trip
        for parm, want in SPEC.items():
            got = shader.parmTuple(parm).eval()
            expect = want if isinstance(want, tuple) else (want,)
            for g, w in zip(got, expect):
                self.assertAlmostEqual(g, w, places=5,
                                       msg="%s did not survive" % parm)

    def test_reimport_is_repeatable(self):
        """Importing the same asset twice must yield two independent working nodes - not a collision or a half-wired copy."""
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

    @unittest.skipUnless(sys.platform != "win32",  # -- the failure half --
                         "chmod cannot make a directory unwritable on "
                         "Windows - the failure this test injects does "
                         "not happen there")
    def test_failed_save_leaves_no_phantom_row(self):
        """A save whose file write fails must not register the asset - a row without files is the phantom that looks fine in the grid until the day it is needed, where files without a row are the safe direction. Skipped on Windows because chmod cannot make a directory unwritable there, so the injected failure never happens; restoring that coverage needs a different injection, not a weaker assertion. ▸r/platform-files"""
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
        """An index row whose .mat is gone - the phantom this suite exists to prevent - must refuse to import with a REASON, not a traceback, and leave no debris in /mat."""
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
    """The Redshift and Octane saves are ONE function, told which thumbnail to run BY NAME. NO TEST IN THE SUITE BUILDS A REDSHIFT OR OCTANE MATERIAL, so neither path runs - the gap is the FIXTURES, not the machine (▸r/renderer-plugins) - and a mistyped thumbnail name would surface for the first time on a real save, after the files were written. These two read the source instead. ▸p/source-derived-tests"""

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

    def test_every_thumbnail_named_there_actually_exists(self):
        """WHAT WOULD BREAK THIS: renaming a `create_thumb_*` method, or a typo in the name passed to the shared save - neither of which raises until a real Redshift or Octane material is saved."""
        from amaze.render import thumbs as thumbs_mod
        named = [args[-1] for args in self._shared_calls() if args]
        self.assertTrue(named, "no thumbnail method names found to check")
        for name in named:
            self.assertTrue(
                hasattr(thumbs_mod.ThumbNailRenderer, name),
                "the shared save dispatches to ThumbNailRenderer.%s, "
                "which does not exist - a save on a machine with that "
                "renderer would raise after writing the files" % name)


class ARedshiftImportReadsItsInterfaceOnce(unittest.TestCase):
    """A Redshift or Octane import reads its `.interface` once, and logs its routing only when on."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.row = next(r for r, a in enumerate(self.model.assets)
                        if a.name == "Metal")

    def _import(self, renderer):
        """Import the fixture's Metal as `renderer` into /mat; answers the `.interface` read count."""
        self.model.assets[self.row].renderer = renderer
        reads = []
        real_open = open

        def counting_open(path, *args, **kwargs):
            if str(path).endswith(".interface"):
                reads.append(path)
            return real_open(path, *args, **kwargs)

        with mock.patch.object(nodes, "open", counting_open, create=True):
            ok, reason, created = self.model.import_asset_to_scene(
                self.model.index(self.row, 0), target="mat")
        for node in created:
            self.addCleanup(node.destroy)
        self.assertTrue(ok, reason)
        return len(reads)

    def test_each_renderer_reads_the_interface_once(self):
        for renderer in ("Redshift", "Octane"):
            with self.subTest(renderer=renderer):
                self.assertEqual(1, self._import(renderer),
                                 "the import re-read its .interface")


class TestUnsafeAssetIds(unittest.TestCase):
    """An id out of library.json becomes a FILENAME, so it decides which file the loader opens - and the app does not author the index alone, since a library can arrive edited, synced or damaged. Both halves are tested: the boundary check that rejects the shape, and the containment that catches an escape the shape check missed."""

    def test_the_real_shapes_are_accepted_and_traversal_is_refused(self):
        """Guards the guard: "32 hex only" would refuse the fixture's legacy timestamp ids and "-1"."""
        for good in ("00755b7004824333af08d921462fa3ae",
                     "139888336268658010", "-1", "a", "A_b-c.d"):
            self.assertTrue(material.is_safe_asset_id(good), good)
        for bad in ("../../.ssh/authorized_keys", "..", ".",
                    "a/b", "a\\b", "", "x" * 65, "a b", "a\x00b"):
            self.assertFalse(material.is_safe_asset_id(bad), repr(bad))

    def test_contained_join_refuses_an_escape_and_a_symlink_out(self):
        """The symlink the shape check cannot see: a clean id, and a link planted in the asset folder."""
        base = tempfile.mkdtemp(prefix="amaze_contain_")
        self.addCleanup(shutil.rmtree, base, True)
        inside = hostos.contained_join(base, "mat/", "asset.mat")
        self.assertTrue(inside.startswith(base))
        with self.assertRaises(hostos.PathEscape):
            hostos.contained_join(base, "mat/", "../../escaped.mat")
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        os.makedirs(os.path.join(base, "mat"))
        os.symlink(outside, os.path.join(base, "mat", "away"))
        with self.assertRaises(hostos.PathEscape):
            hostos.contained_join(base, "mat", "away", "asset.mat")

    def test_payload_path_composes_with_or_without_a_separator_and_contains(self):
        """Concatenation gave `<lib>mat/abc.mat` for a dir saved without its separator."""
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

        class _Unslashed(_P):
            dir = base                      # no trailing separator

        self.assertEqual(    # normpath BOTH sides: asset_dir carries a literal "mat/"
            os.path.normpath(os.path.join(base, "mat", "abc.mat")),
            os.path.normpath(material.payload_path(_Unslashed, "abc",
                                                   ".mat")),
            "a library path without its trailing separator composed "
            "wrong - which is what concatenation did here")
        with self.assertRaises(hostos.PathEscape):    # the PATH guard, beside the RECORD's
            material.payload_path(_P, "../../.ssh/authorized_keys", ".mat")

    def test_an_import_with_a_traversal_id_is_refused(self):
        """End to end through the real importer: the refusal names the material, nothing is created, and the file it would have read is never opened."""
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
    """`.interface` is asCode() output - Python whose only documented contract is that it RUNS - chosen by an id read verbatim out of library.json. It is read for its builder type by regex and nothing more; the container's own parameter interface comes from a PARSED sidecar. These prove the execution is gone, not merely guarded. ▸r/interface-contents"""

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

        self.model.import_asset_to_scene(self.model.index(row, 0), target="mat")  # succeed or refuse, either is fine - what must NOT happen is the payload running, and asserting "it still imports" would pass with exec() restored
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
        """A promoted ramp survives capture by a route worth pinning, because reading the code suggests otherwise: `json.dumps` sits OUTSIDE the per-parm guard and `hou.Ramp` is not serialisable, so capture LOOKS one dialled ramp away from raising `TypeError` past `save_asset_pair`. Measured 2026-08-10 that it is not - a ramp's container parm reports `isAtDefault()` True even once dialled, so `capture_builder` never evaluates it and walks the backing Float components instead. So this pins the round TRIP, not a refusal: the shape comes back from the dialog script and the values from the components."""
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
        """The guard the measurement above says nothing reaches today: `json.dumps` runs over the whole document AFTER the loop, so a value it refuses raises `TypeError`, which `save_asset_pair` does not catch - and a sidecar that cannot be built must not cost the asset. No shipped parm type gets there; this pins the behaviour for the one that eventually does. ▸p/asset-write-unit"""
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
        """Every asset saved before the format existed has none, and the loader degrades rather than refusing."""
        self.assertEqual({}, nodes.read_builder_sidecar(
            os.path.join(self.prefs.dir, "does-not-exist.builder.json")))
        broken = os.path.join(self.prefs.dir, "broken.builder.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        with test_support.captured_log() as log:
            self.assertEqual({}, nodes.read_builder_sidecar(broken))
        self.assertTrue(log.matching("builder sidecar unreadable", "import"),
                        "a damaged sidecar was swallowed silently")


class UpdateExistingIsGuardedAgainstTheOtherSessionTest(unittest.TestCase):
    """Two sessions both doing a structural Update Existing to the same id silently last-write-wins the .mat/.interface pair - the one write that stays exclusive even after Versions, because content is outside the index merge entirely."""

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
        """A session's own write must not trip its own guard - two updates in a row from one session are ordinary use."""
        row = next(r for r in range(self.model.rowCount())  # is_karma_renderer, not a literal match: the stored value is "MaterialX" but the renderer property NORMALISES, so matching the raw string finds nothing
                   if material.is_karma_renderer(
                       self.model.assets[r].renderer))
        node = _build_material(self.staging, "update_guard_probe")
        first = self.model.update_asset_content(row, node)
        self.assertTrue(first, "premise: the first update lands")
        second = self.model.update_asset_content(row, node)
        self.assertTrue(second,
                        "a session's own write tripped its own guard - "
                        "the baseline was not refreshed")


class AStaleCompanionGoesWhateverTheExtension(unittest.TestCase):

    def test_an_update_with_no_cop_net_removes_the_companion(self):
        """The companion's name follows the extension preference, as every other asset file does."""
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")
        prefs = test_support.fixture_prefs(self)
        prefs._ext = ".cpio"
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs)
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        row = next(r for r in range(model.rowCount())
                   if material.is_karma_renderer(model.assets[r].renderer))
        companion = model.asset_files(model.assets[row].mat_id)["cop"]
        self.assertTrue(companion.endswith("_cop.cpio"), companion)
        with open(companion, "w", encoding="utf-8") as handle:
            handle.write("a companion the new network no longer uses")
        node = _build_material(staging, "stale_companion_probe")
        self.assertTrue(model.update_asset_content(row, node),
                        "premise: the update lands")
        self.assertFalse(os.path.exists(companion),
                         "the stale companion stayed beside the asset")


class StructureSignatureTest(unittest.TestCase):
    """The Versions decision rule: same nodes, same wiring, only values differ -> a new version; anything else -> the structural path. The signature is what answers it, so its two directions ARE the feature's correctness. ▸p/structure-signature"""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_value_edits_and_layout_moves_keep_the_signature(self):
        builder = _build_material(self.staging, "sig_keep_probe")
        before = nodes.structure_signature(builder)
        shader = _shader_of(builder)
        scalar = next(parm for parm in shader.parms()    # a SCALAR float: a colour's .parm() is None
                      if parm.parmTemplate().numComponents() == 1
                      and parm.parmTemplate().type()
                      == hou.parmTemplateType.Float)
        scalar.set(scalar.eval() + 0.111)
        self.assertEqual(before, nodes.structure_signature(builder),
                         "a value edit changed the structure signature - "
                         "every parameter tweak would take the structural "
                         "path and Versions would never fire")
        for child in builder.children():
            child.move(hou.Vector2(3.0, -2.0))
        self.assertEqual(before, nodes.structure_signature(builder),
                         "canvas layout leaked into the signature")

    def test_an_added_node_or_a_rewire_changes_it(self):
        builder = _build_material(self.staging, "sig_change_probe")
        before = nodes.structure_signature(builder)
        image = builder.createNode("mtlximage", "sig_added")
        added = nodes.structure_signature(builder)
        self.assertNotEqual(before, added,
                            "an added node did not change the signature - "
                            "a structural edit would silently become a "
                            "version")
        _shader_of(builder).setInput(0, image)
        self.assertNotEqual(added, nodes.structure_signature(builder),
                            "a rewire did not change the signature")

    def test_staged_asset_loads_and_cleans_up_even_when_the_loader_raises(self):
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

        def boom(_node):
            raise RuntimeError("loader failure")

        with self.assertRaises(RuntimeError):
            nodes.staged_asset(self.prefs, mat, boom)
        self.assertEqual(obj_before, set(hou.node("/obj").children()),
                         "a raising loader stranded the staging network")


class AnUnreadablePayloadRefusesWithoutAScreenTest(unittest.TestCase):
    """`load_items_strict` ABSORBS the unreadable file and returns a reason, so its callers' `except OSError` cannot fire - and the dialog inside one would be an AttributeError with no screen to raise it on. ▸r/status-bar"""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_a_missing_payload_comes_back_as_a_reason_not_an_OSError(self):
        """The contract the callers are written against: a reason string, never a raise."""
        missing = os.path.join(self.prefs.dir, "no-such-asset.mat")
        self.assertFalse(os.path.exists(missing))
        problem = nodes.load_items_strict(self.staging, missing)
        self.assertTrue(problem, "an unreadable payload reported nothing, so "
                                 "the caller cannot tell it apart from a "
                                 "clean load")
        self.assertIn("could not be read", problem)
        as_dir = os.path.join(self.prefs.dir, "payload-is-a-directory.mat")    # getsize ANSWERS for a folder
        os.makedirs(as_dir, exist_ok=True)
        self.addCleanup(os.rmdir, as_dir)
        problem = nodes.load_items_strict(self.staging, as_dir)
        self.assertTrue(problem, "a directory in the payload slot loaded as "
                                 "if it were a material")
        self.assertIn(
            os.path.basename(as_dir), problem,
            "the refusal does not name the file, so the reader is left with "
            "Houdini's bare sentence: %r" % problem)

    def test_both_imports_refuse_through_hou_error_with_no_ui_present(self):
        """Headless, a missing payload is a hou.Error with a reason, never a dialog's AttributeError."""
        self.assertFalse(hasattr(hou, "ui"),
                         "this test needs a headless hou to mean anything")
        for method in ("load_items_file", "load_items_file_mtlx"):
            with self.subTest(method):
                handler = nodes.NodeHandler(self.prefs)
                handler._builder_node = self.staging
                mat = material.Material(name="gone", mat_id="no-such-asset-id")
                with self.assertRaises(hou.Error) as caught:
                    getattr(handler, method)(mat)
                self.assertIn("could not be read", str(caught.exception))

    def _an_oserror_reaches_no_screen(self, method: str):
        """Force the OSError the callers guard against and let it arrive: whatever handles it must not be a dialog, because there is no screen to raise one on."""
        handler = nodes.NodeHandler(self.prefs)
        handler._builder_node = self.staging
        mat = material.Material(name="gone", mat_id="no-such-asset-id")

        from unittest.mock import patch

        def unreadable(_node, _file_name):
            raise OSError(5, "Input/output error")

        with patch.object(nodes, "load_items_strict", unreadable):
            try:
                getattr(handler, method)(mat)
            except AttributeError as crash:
                self.fail("the refusal reached hou.ui and became a crash: %s"
                          % crash)
            except (OSError, hou.Error):
                return
        self.fail("%s swallowed a real read failure and reported nothing"
                  % method)

    def test_a_read_failure_never_becomes_a_crash_on_either_import(self):
        """▸r/status-bar - hou.ui does not exist headless."""
        for method in ("load_items_file", "load_items_file_mtlx"):
            with self.subTest(method):
                self._an_oserror_reaches_no_screen(method)


class AFreshHandlerNamesNoBuilder(unittest.TestCase):
    """Before any import a handler holds no builder, so a cleanup cannot take `/stage` for one."""

    def test_the_builder_starts_empty(self):
        handler = nodes.NodeHandler(test_support.fixture_prefs(self))
        self.assertIsNone(handler.builder_node)


class ASavedAssetRebuildsInsideAScratchNetwork(unittest.TestCase):
    """`NodeHandler.rebuild_saved` puts a saved asset back together in a scratch network for reading."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.karma = next(
            self.model.assets[r] for r in range(self.model.rowCount())
            if material.is_karma_renderer(self.model.assets[r].renderer))
        with hou.undos.disabler():
            self.scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.scratch.destroy)

    def test_a_karma_asset_lands_in_the_scratch_and_an_unknown_one_is_refused(self):
        obj_before = set(hou.node("/obj").children())
        builder = nodes.NodeHandler(self.prefs).rebuild_saved(self.karma, self.scratch)
        self.assertEqual(self.scratch.path(), builder.parent().path())
        self.assertTrue(builder.children(), "the builder came back empty")
        self.assertEqual(obj_before, set(hou.node("/obj").children()))
        odd = material.Material(name="odd", renderer="", mat_id=self.karma.mat_id)
        with self.assertRaises(hou.OperationFailed) as caught:
            nodes.NodeHandler(self.prefs).rebuild_saved(odd, self.scratch)
        self.assertIn("unrecognised renderer", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
