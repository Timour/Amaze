"""Save/load round-trip on real fixture files: values survive disk, a failed save leaves no row."""

import os
import stat
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(  # three dirnames reach python/; four would test the install ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import material_files  # noqa: E402
from amaze.core import material, renderers  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402

SPEC = {  # distinctive non-default values: the point is that these numbers survive disk
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

    return nodes.build_karma_material(parent, name, produce).builder  # by name: the engine returns a nodes.KarmaMaterial, not a bare pair


def _shader_of(builder: hou.Node):
    return next(n for n in builder.children()
                if n.type().name() == "mtlxstandard_surface")


class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here

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
        """A bare shader's save must not archive the builder's connector, or the import renders black."""
        builder = _build_material(self.staging, "bare_probe")
        shader = _shader_of(builder)
        texture = builder.createNode("mtlximage")
        shader.setInput(1, texture)

        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, shader, "Bare", "", False)
        asset, = test_support.arrived(self.model, held)

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

    @unittest.skipUnless(test_support.renderer_loaded("Redshift"),
                         "the Redshift plugin is not loaded")
    def test_an_import_keeps_its_builder(self):
        """A rebuilt container is kept and moved, not gutted into loose VOPs in /mat."""
        mat_ctx = hou.node("/mat") or hou.node("/").createNode("mat")
        source = mat_ctx.createNode("redshift_vopnet", "rs_src")
        source.setGenericFlag(hou.nodeFlag.Material, True)

        before = {n.path() for n in mat_ctx.children()}
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, source, "RedshiftProbe", "", False)
        asset, = test_support.arrived(self.model, held)
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
        """SOP imports reuse one matnet, as LOP imports reuse a materiallibrary, never one per import."""
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

    def _failing_lop_import(self, context):
        """Import a Karma asset whose `.mat` is damaged into `context`; answers the import's ok."""
        asset = next(a for a in self.model.assets
                     if renderers.is_karma(a.renderer))
        payload = material.payload_path(self.prefs, asset.mat_id,
                                        self.prefs.ext)
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write("not an items file")
        ok, _reason, _created = nodes.NodeHandler(
            self.prefs).import_asset_to_scene(
                asset, target="lop", context_node=context)
        return ok

    def _libraries(self, stage):
        return [c.name() for c in stage.children()
                if c.type().name() == "materiallibrary"]

    def test_a_lop_import_lands_in_the_library_it_is_handed_or_nowhere(self):
        """Outside a Material Library an import makes nothing; inside one, a bad load leaves it."""
        from amaze import messages
        stage = hou.node("/obj").createNode("lopnet", "lop_landing_probe")
        self.addCleanup(stage.destroy)
        ok, reason, _created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            self._karma_asset(), target="lop", context_node=stage)
        self.assertFalse(ok, "an import outside a Material Library went ahead")
        self.assertEqual(messages.LOP_IMPORT_OUTSIDE_LIBRARY, reason)
        self.assertEqual([], self._libraries(stage),
                         "the import made a library on its own")
        theirs = stage.createNode("materiallibrary", "theirs")
        self.assertFalse(self._failing_lop_import(theirs),
                         "premise: a damaged .mat must fail the import")
        self.assertEqual(["theirs"], self._libraries(stage),
                         "a failed import removed the library it was handed")

    def test_karma_destination_is_the_library_or_nothing_in_solaris(self):
        """The online import and Generate land in the current Material Library, or nowhere."""
        stage = hou.node("/obj").createNode("lopnet", "destination_probe")
        self.addCleanup(stage.destroy)
        with mock.patch.object(nodes.NodeHandler, "get_current_network_node",
                               return_value=stage):
            self.assertIsNone(nodes.karma_destination(self.prefs),
                              "a LOP network outside a library was given a destination")
        self.assertEqual([], self._libraries(stage),
                         "karma_destination made a library on its own")
        theirs = stage.createNode("materiallibrary", "theirs")
        with mock.patch.object(nodes.NodeHandler, "get_current_network_node",
                               return_value=theirs):
            self.assertEqual(theirs, nodes.karma_destination(self.prefs))

    def _karma_asset(self):
        return next(a for a in self.model.assets
                    if renderers.is_karma(a.renderer))

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

    def test_a_companion_that_raises_leaves_the_library_it_was_handed(self):
        stage = hou.node("/obj").createNode("lopnet", "companion_raise_probe")
        self.addCleanup(stage.destroy)
        theirs = stage.createNode("materiallibrary", "theirs")
        handler = nodes.NodeHandler(self.prefs)

        def refusing(mat, beside):
            raise hou.OperationFailed("companion refused")

        handler.restore_cop_companion = refusing
        self._assert_refused_plainly(handler, theirs)
        self.assertEqual(["theirs"], self._libraries(stage),
                         "the import removed the library it was handed when "
                         "the COP companion raised")
        self.assertIsNone(handler._context_override,
                          "the import kept the context it was handed")

    def test_a_staging_failure_takes_back_the_companion_restored(self):
        """The companion is restored before the staging network exists, and both are the import's."""
        stage = hou.node("/obj").createNode("lopnet", "staging_raise_probe")
        self.addCleanup(stage.destroy)
        library = stage.createNode("materiallibrary", "theirs")
        real_node = hou.node
        self.addCleanup(lambda: [n.destroy() for n in
                                 [real_node("/obj/staging_probe_cops")]
                                 if n is not None])
        handler = nodes.NodeHandler(self.prefs)
        handler.restore_cop_companion = lambda mat, beside: real_node(
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
            self._assert_refused_plainly(handler, library)
        self.assertIsNone(real_node("/obj/staging_probe_cops"),
                          "the import left the COP companion it restored")
        self.assertEqual(["theirs"], self._libraries(stage))

    def test_a_builder_is_saved_whole_with_its_own_data(self):
        """A MaterialX builder saves whole, so data on the builder itself comes back with it."""
        builder = _build_material(self.staging, "whole_probe")
        builder.setUserData("amaze_whole_probe", "1")
        held = test_support.asset_ids(self.model)
        self.assertEqual("Karma", material_actions.add_asset(
            self.model, builder, "", "", False))
        asset, = test_support.arrived(self.model, held)
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            asset, target="mat")
        self.assertTrue(ok, reason)
        self.assertEqual("1", created[0].userData("amaze_whole_probe"),
                         "the builder was saved as its contents, so its own data stayed behind")

    def test_saved_material_survives_disk_and_reimports(self):  # -- the round-trip --
        rows_before = self.model.rowCount()
        builder = _build_material(self.staging, "roundtrip_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "roundtrip,test", False)

        self.assertEqual(self.model.rowCount(), rows_before + 1)  # registered once, stamped for re-saves
        mat_id = str(test_support.arrived(self.model, held)[0].mat_id)
        self.assertEqual(builder.userData("assetlib_id"), mat_id)

        base = os.path.join(self.prefs.dir, self.prefs.asset_dir, mat_id)  # both halves of the archive exist and are non-empty
        for path in (base + self.prefs.ext, base + ".interface"):
            self.assertTrue(os.path.exists(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)

        test_support.reset_database_singletons()  # persistence: a fresh model over the same dir, so the row comes from library.json
        reloaded = library_mod.MaterialLibrary(preferences=self.prefs)
        row = reloaded.find_asset_row_by_id(mat_id)
        self.assertNotEqual(row, -1, "saved row missing after reload")
        asset = reloaded.assets[row]
        self.assertEqual(asset.name, "roundtrip_mat")
        self.assertIn("RoundTrip", asset.categories)

        ok, reason, _created = material_actions.import_asset_to_scene(reloaded,   # RE-IMPORT through the real importer, into /mat
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
        """Importing the same asset twice yields two independent working nodes, not a collision."""
        builder = _build_material(self.staging, "twice_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
        row = self.model.find_asset_row_by_id(
            test_support.arrived(self.model, held)[0].mat_id)
        for _ in range(2):
            ok, reason, _created = material_actions.import_asset_to_scene(self.model,
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
        """A save whose file write fails registers no row; skipped on Windows (no chmod) ▸r/platform-files"""
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
                material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
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
        """An index row whose .mat is gone refuses to import with a reason and leaves no debris in /mat."""
        builder = _build_material(self.staging, "vanishing_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
        mat_id = str(test_support.arrived(self.model, held)[0].mat_id)
        row = self.model.find_asset_row_by_id(mat_id)
        os.remove(os.path.join(self.prefs.dir, self.prefs.asset_dir,
                               mat_id + self.prefs.ext))
        ok, reason, _created = material_actions.import_asset_to_scene(self.model,
            self.model.index(row, 0), target="mat"
        )
        self.assertFalse(ok)
        self.assertTrue(reason.strip(), "the refusal gave the artist no reason")
        fresh = [n for n in hou.node("/mat").children()
                 if n not in self._mat_before
                 and n.userData("assetlib_id") == mat_id]
        self.assertEqual(fresh, [], "failed import left debris in /mat")


class EveryMaterialSaveIsOneSave(unittest.TestCase):
    """One method writes every renderer's material files, the COP save its own ▸p/source-derived-tests"""

    def test_one_method_writes_the_pair(self):
        import ast
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "render", "nodes.py")
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        writers = sorted(
            func.name for func in ast.walk(tree)
            if isinstance(func, ast.FunctionDef)
            and any(isinstance(call, ast.Call)
                    and getattr(call.func, "attr", "") == "save_asset_pair"
                    for call in ast.walk(func)))
        self.assertEqual(
            ["_save_copy", "save_node_cop"], writers,
            "a material save writes its files outside `_save_copy`, so its copy, "
            "adoption or thumbnail can drift from every other renderer's")


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

        with mock.patch.object(nodes, "open", counting_open, create=True), \
                mock.patch.object(material_files, "open", counting_open, create=True):
            ok, reason, created = material_actions.import_asset_to_scene(self.model,
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
    """An id from library.json becomes a filename: the shape check and the containment are tested."""

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
        """End to end: a traversal id is refused by name, nothing is created, the file is never opened."""
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
        ok, reason, _created = material_actions.import_asset_to_scene(model, model.index(row, 0),
                                                 target="mat")
        self.assertFalse(ok, "a traversal id was imported")
        self.assertIn("tampered", reason)
        self.assertEqual(before, set(hou.node("/mat").children()),
                         "a refused import still created a node")


class TestInterfaceIsNeverExecuted(unittest.TestCase):
    """`.interface` is code chosen by an id; it is read by regex, never executed ▸r/interface-contents"""

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

        material_actions.import_asset_to_scene(self.model, self.model.index(row, 0), target="mat")  # succeed or refuse; only the payload running fails, so do not assert it imports
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

    def _animated_builder(self):
        """A builder with a Python expression and two parms keyed at frames 1 and 25."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")
        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_py", "Py", 1))
        group.append(hou.FloatParmTemplate("amaze_keyed", "Keyed", 1))
        group.append(hou.StringParmTemplate("amaze_skeyed", "SKeyed", 1))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_py").setExpression("hou.frame() * 3", language=hou.exprLanguage.Python)
        keys = []
        for frame, value in ((1, 0.0), (25, 10.0)):
            key = hou.Keyframe()
            key.setFrame(frame)
            key.setValue(value)
            key.setExpression("linear()", hou.exprLanguage.Hscript)
            keys.append(key)
        builder.parm("amaze_keyed").setKeyframes(keys)
        skeys = []
        for frame, text in ((1, "'early'"), (25, "'late'")):
            key = hou.StringKeyframe()
            key.setFrame(frame)
            key.setExpression(text, hou.exprLanguage.Python)
            skeys.append(key)
        builder.parm("amaze_skeyed").setKeyframes(skeys)
        return staging, builder

    def test_an_expression_keeps_its_language_and_keys_stay_keys(self):
        """`setExpression` without a language reads Python as HScript; several keys are no expression."""
        staging, builder = self._animated_builder()
        self.addCleanup(hou.setFrame, hou.frame())
        captured = json.loads(nodes.capture_builder(builder))
        fresh = staging.createNode("subnet")
        nodes.apply_builder(fresh, captured)
        py = fresh.parm("amaze_py")
        self.assertEqual(hou.exprLanguage.Python, py.expressionLanguage(),
                         "a Python expression came back in another language")
        hou.setFrame(2)
        self.assertAlmostEqual(6.0, py.eval(), 5)
        keyed = fresh.parm("amaze_keyed")
        self.assertEqual(2, len(keyed.keyframes()),
                         "the keyframes came back baked to one value")
        hou.setFrame(13)
        self.assertAlmostEqual(5.0, keyed.eval(), 4)
        skeyed = fresh.parm("amaze_skeyed")
        self.assertEqual(2, len(skeyed.keyframes()), "the string keys were lost")
        hou.setFrame(30)
        self.assertEqual("late", skeyed.eval())

    def test_a_sidecar_stays_readable_on_both_sides_of_the_keyframe_change(self):
        """An old sidecar loads as before, and every new value still carries a field an old reader reads."""
        staging, builder = self._animated_builder()
        for name, spec in json.loads(nodes.capture_builder(builder))["values"].items():
            self.assertTrue({"expr", "str", "val"} & set(spec),
                            "%s has nothing an older Amaze can apply: %r" % (name, spec))
        old = {"dialog_script": builder.parmTemplateGroup().asDialogScript(),
               "values": {"amaze_keyed": {"expr": "$F * 2"}, "amaze_py": {"val": 0.5}}}
        fresh = staging.createNode("subnet")
        nodes.apply_builder(fresh, old)
        self.assertEqual("$F * 2", fresh.parm("amaze_keyed").expression())
        self.assertEqual(hou.exprLanguage.Hscript, fresh.parm("amaze_keyed").expressionLanguage())
        self.assertAlmostEqual(0.5, fresh.parm("amaze_py").eval(), 5)

    def test_a_promoted_RAMP_round_trips_through_its_components(self):
        """A promoted ramp round-trips: shape from the dialog script, values from its Float components."""
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
        """A value the sidecar cannot serialise costs only that parm, never the asset ▸p/asset-write-unit"""
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
        """Assets saved before the sidecar format have none; the loader degrades rather than refusing."""
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
    """Two structural updates to one id from two sessions must not last-write-win the asset pair."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
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
        with test_support.captured_log() as log, \
                self.assertRaises(material_actions.UpdateRefused,
                                  msg="the update overwrote content another session "
                                      "wrote since this one read it") as refused:
            material_actions.update_asset_content(self.model, row, node)

        self.assertEqual(messages.UPDATE_REFUSED_CHANGED_ON_DISK, str(refused.exception))
        self.assertEqual([], log.messages("alert"),
                         "the refusal alerted on its own, beside the save's one message")
        now = open(self.model.asset_files(mat.mat_id)["mat"],
                   "rb").read()
        self.assertEqual(theirs, now,
                         "the refusal still modified their file")
        self.assertNotEqual(before, now, "premise check")

    def test_our_own_update_rebaselines(self):
        """A session's own write must not trip its own guard: two updates in a row are ordinary use."""
        row = next(r for r in range(self.model.rowCount())  # the stored value may be MaterialX
                   if renderers.is_karma(
                       self.model.assets[r].renderer))
        node = _build_material(self.staging, "update_guard_probe")
        first = material_actions.update_asset_content(self.model, row, node)
        self.assertTrue(first, "premise: the first update lands")
        second = material_actions.update_asset_content(self.model, row, node)
        self.assertTrue(second,
                        "a session's own write tripped its own guard - "
                        "the baseline was not refreshed")


class AStaleCompanionGoesWhateverTheExtension(unittest.TestCase):

    def test_an_update_with_no_cop_net_removes_the_companion(self):
        """The companion's name follows the extension preference, as every other asset file does."""
        test_support.pin_env(self, "OCIO", "/dev/null")
        prefs = test_support.fixture_prefs(self)
        prefs._ext = ".cpio"
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs)
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        row = next(r for r in range(model.rowCount())
                   if renderers.is_karma(model.assets[r].renderer))
        companion = model.asset_files(model.assets[row].mat_id)["cop"]
        self.assertTrue(companion.endswith("_cop.cpio"), companion)
        with open(companion, "w", encoding="utf-8") as handle:
            handle.write("a companion the new network no longer uses")
        node = _build_material(staging, "stale_companion_probe")
        self.assertTrue(material_actions.update_asset_content(model, row, node),
                        "premise: the update lands")
        self.assertFalse(os.path.exists(companion),
                         "the stale companion stayed beside the asset")


class AnUpdateWhoseListWriteIsRefused(unittest.TestCase):
    """The files are new, the record waits in memory, and the save's own alert is the only dialog."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def _listed(self, mat_id):
        with open(self._index(), encoding="utf-8") as handle:
            return next(row for row in json.load(handle)["assets"]
                        if str(row.get("id")) == mat_id)

    def _index(self):
        return os.path.join(self.prefs.dir, self.model.DB_FILENAME)

    def test_the_answer_says_so_and_the_next_save_writes_the_record(self):
        row = next(r for r in range(self.model.rowCount())
                   if renderers.is_karma(self.model.assets[r].renderer))
        mat = self.model.assets[row]
        mat_id = str(mat.mat_id)
        network = self.model.asset_files(mat_id)["mat"]
        with open(network, "rb") as handle:
            before = handle.read()
        listed = self._listed(mat_id)
        node = _build_material(self.staging, "refused_list_probe")
        with test_support.full_disk_for(self._index()), test_support.captured_log() as log:
            answer = material_actions.update_asset_content(self.model, row, node)
        with open(network, "rb") as handle:
            self.assertNotEqual(before, handle.read(), "premise: the update wrote no files")
        self.assertEqual(listed, self._listed(mat_id), "premise: the list write went through")
        self.assertNotEqual(listed["date"], mat.date, "premise: the record kept its date")
        self.assertTrue(answer, "the files are new, yet the update answered that nothing was "
                        "written, which the panel shows as Update failed")
        self.assertIsInstance(answer, library_mod.ListNotSaved,
                              "the update answered a plain success while its list entry "
                              "was not saved, so the panel could not say so")
        self.assertEqual(1, len(log.messages("alert")),
                         "a second alert joined the save's own: %s" % log.messages("alert"))
        self.assertTrue(log.matching("could not save the library", "alert"),
                        log.messages("alert"))
        self.assertTrue(log.matching("list was not saved", "library"),
                        "the update did not record that its list write was refused")
        self.assertTrue(self.model.save(), "premise: the next save was refused too")
        self.assertEqual(mat.date, self._listed(mat_id)["date"],
                         "the next save that works did not write the update's record")


class AnAddWhoseListWriteIsRefused(unittest.TestCase):
    """A new material whose list write fails: in the grid, its answer marked, one alert only."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_the_answer_says_so_and_the_library_alert_is_the_only_one(self):
        node = _build_material(self.staging, "refused_add_probe")
        held = test_support.asset_ids(self.model)
        index = os.path.join(self.prefs.dir, self.model.DB_FILENAME)
        with test_support.full_disk_for(index), test_support.captured_log() as log:
            answer = material_actions.add_asset(self.model, node, "", "", False)
        self.assertEqual(1, len(test_support.arrived(self.model, held)),
                         "premise: the new tile is not in the grid")
        self.assertIsInstance(answer, library_mod.ListNotSaved,
                              "the add answered a plain success while its list entry "
                              "was not saved, so the panel could not say so")
        self.assertEqual(1, len(log.messages("alert")),
                         "a second alert joined the library's own: %s" % log.messages("alert"))
        self.assertTrue(log.matching("could not save the library", "alert"),
                        log.messages("alert"))


class StructureSignatureTest(unittest.TestCase):
    """Versions rule: only values differ means a new version, else structural ▸p/structure-signature"""

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
                   if renderers.is_karma(model.assets[r].renderer))
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
    """An unreadable payload refuses with a reason, never a dialog with no screen ▸r/status-bar"""

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
        """Force the OSError the callers guard and let it arrive: its handler must not be a dialog."""
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
            if renderers.is_karma(self.model.assets[r].renderer))
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
